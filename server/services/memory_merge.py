"""MEM1 (v0.1.64, memory plan item A1): before Arslan stores a new memory entry, is there one that says the same?

`dedup_key` and fact_dedup catch the same words; the user's machine had the same meaning stored three times in
different words. So the nearest live entries of the same kind, scope and always-in-view set (at most NEAREST, by the
local relevance scorer) are asked about, one by one, with the judge's `memory.merge` point (the question lessons
use; threshold 0.8, judgment.REGISTRY). The first "same" is the match; MemoryRepository.merge_into then decides what
the write may do to it (INB2: a write that would wait never refreshes an active entry).

Cost: at most NEAREST judge calls per write, each about 300 tokens in and 15 out on the user's fast model slot,
under the judge's daily cap. No answer (judging off, the cap, a timeout, no model) is no merge, never a merge on a
guess: the write is stored as it is today.
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


async def same_meaning(content: str, *, kind: str, scope, core: str | None, owner_id: str,
                       conversation_id: str | None) -> Match | None:
    """The live entry (active, proposed or paused) that says the same as `content`, or None."""
    from arslan.companion import memory_relevance
    from server.db import session as db_session
    from server.db.models import MemoryEntry, MemoryRevision
    from server.services import judgment
    wanted = memory_relevance.terms(content) - _ABOUT_EVERYONE
    if not wanted:
        return None
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(MemoryEntry.id, MemoryEntry.version, MemoryRevision.content,
                                        MemoryRevision.structured_value).join(
            MemoryRevision, MemoryRevision.id == MemoryEntry.current_revision_id).where(
            MemoryEntry.owner_id == owner_id, MemoryEntry.kind == kind, MemoryEntry.scope_kind == scope.kind,
            MemoryEntry.scope_id.is_(None) if scope.id is None else MemoryEntry.scope_id == scope.id,
            MemoryEntry.status.in_(("active", "proposed", "paused")), MemoryEntry.superseded_by.is_(None),
        ).order_by(MemoryEntry.updated_at.desc()).limit(SCAN_LIMIT))).all()
    scored = [(len(wanted & memory_relevance.terms(text or "")), entry_id, version, text)
              for entry_id, version, text, structured in rows if (structured or {}).get("core") == core]
    nearest = sorted((row for row in scored if row[0] > 0), key=lambda row: -row[0])[:NEAREST]
    point = judgment.REGISTRY["memory.merge"]
    for _, entry_id, version, text in nearest:
        verdict = await judgment.judge("memory.merge", {"candidate": content, "existing": text},
                                       conversation_id=conversation_id)
        if verdict is None:
            return None                                   # no answer: no merge on a guess
        if verdict.yes(point.threshold):
            return Match(entry_id, version)
    return None
