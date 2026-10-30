"""MEM1 (v0.1.64, memory plan item A1): before Arslan stores a new memory entry, is there one that says the same?

`dedup_key` and fact_dedup catch the same words; the user's machine had the same meaning stored three times in
different words. So the nearest live entries of the same kind, scope and always-in-view set (at most NEAREST, by the
local relevance scorer) are asked about, one by one, with the judge's `memory.same` point: the same thing, the
candidate adding nothing (threshold 0.8, judgment.REGISTRY). The first "same" is the match; MemoryRepository.merge_into
then decides what the write may do to it (INB2: a write that would wait never refreshes an active entry).

What the judge is shown follows the rule for memory in any prompt (②Main's review of #559, H1): nothing when no memory
may be shown in this context (personal_context.may_show_memory), and only entries whose sensitivity and use that
context allows (personal_context.shown_to_model); a candidate the context could not show is not asked about either.
The judgments ledger keeps the entry's id (`ref`) and digests, never either text (the point's `redact`).

Not merged at all: the user's explicit request to remember something (its words are theirs, M1).

Cost: at most NEAREST judge calls per write, each about 300 tokens in and 15 out on the user's fast model slot, under
`memory.same`'s own daily cap (judgment.MEMORY_SAME_DAILY_CAP). No answer (judging off, the cap, a timeout, no model)
is no merge, never a merge on a guess: the write is stored as it is today.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

NEAREST = 3
SCAN_LIMIT = 200
# Every "about you" entry is about the user: those words are no evidence that two entries say the same thing.
_ABOUT_EVERYONE = frozenset({"user", "users", "用户"})  # lang-check: allow (Chinese input to match)


@dataclass(frozen=True)
class Match:
    id: str
    version: int


async def same_meaning(content: str, *, ctx, kind: str, scope, core: str | None, sensitive: bool) -> Match | None:
    """The live entry (active, proposed or paused) that says the same as `content`, or None."""
    from arslan.companion import memory_relevance
    from arslan.companion.memory import sensitive_words
    from server.db import session as db_session
    from server.db.models import MemoryEntry, MemoryRevision
    from server.services import judgment
    from server.services import personal_context as pc
    if not pc.may_show_memory(ctx) or ctx.explicit_save_ref is not None:
        return None
    sensitivities, uses = pc.shown_to_model(ctx)
    if (sensitive or sensitive_words(content)) and "sensitive" not in sensitivities:
        return None
    wanted = memory_relevance.terms(content) - _ABOUT_EVERYONE
    if not wanted:
        return None
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(MemoryEntry.id, MemoryEntry.version, MemoryRevision.content,
                                        MemoryRevision.structured_value).join(
            MemoryRevision, MemoryRevision.id == MemoryEntry.current_revision_id).where(
            MemoryEntry.owner_id == ctx.owner_id, MemoryEntry.kind == kind, MemoryEntry.scope_kind == scope.kind,
            MemoryEntry.scope_id.is_(None) if scope.id is None else MemoryEntry.scope_id == scope.id,
            MemoryEntry.status.in_(("active", "proposed", "paused")), MemoryEntry.superseded_by.is_(None),
            MemoryEntry.sensitivity.in_(sensitivities), MemoryEntry.use_policy.in_(uses),
        ).order_by(MemoryEntry.updated_at.desc()).limit(SCAN_LIMIT))).all()
    scored = [(len(wanted & memory_relevance.terms(text or "")), entry_id, version, text)
              for entry_id, version, text, structured in rows if (structured or {}).get("core") == core]
    nearest = sorted((row for row in scored if row[0] > 0), key=lambda row: -row[0])[:NEAREST]
    point = judgment.REGISTRY["memory.same"]
    for _, entry_id, version, text in nearest:
        verdict = await judgment.judge("memory.same", {"candidate": content, "existing": text},
                                       ref=f"entry:{entry_id}", conversation_id=ctx.conversation_id)
        if verdict is None:
            return None                                   # no answer: no merge on a guess
        if verdict.yes(point.threshold):
            return Match(entry_id, version)
    return None
