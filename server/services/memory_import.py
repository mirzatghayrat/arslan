"""CAP8b: memories the user pasted from ChatGPT or Claude (the memory plan's item 17).

The text is the message this turn stored, never the model's words: a page or a file the model read can't start an
import. It's split by lines with no model call. MEM1's rules leave out what isn't a memory, and the card says why. A line
that says the same as a stored entry starts unticked and names that entry: ticking it stores it as its own entry, since
the user's words are never folded away (MEM1, M1). Nothing is stored until the user confirms, and then only the lines
they kept, as their own words: plain "about you" preferences, never lessons or notes. The pasted text is shown, not
followed.

A message going to the card leaves post-turn learning first (`learns_after_message_id`; turn_facts), so the card is the
only way in for its lines, and a no or an unticked line holds.

The card is the install card's channel, answered only in the Arslan window, so the phone never gets it.
"""
from __future__ import annotations

import asyncio
import logging
import re

from sqlalchemy import select

from server.db import session as db_session
from server.db.companion_models import ConversationContext, MemoryEntry, MemoryRevision
from server.db.models import ArslanMessage
from server.orchestrator import untrusted
from server.services import memory_merge, turn_facts
from server.services import personal_context as pc
from server.services.memory_repository import repository

from arslan.companion.content_policy import contains_credential, normalized_memory
from arslan.companion.memory import MemoryScope, MemoryWrite, sensitive_words

logger = logging.getLogger(__name__)

KIND = "memory_import"
MAX_ENTRIES = 60
#: The most lines read for one card, however many are left out (a log pasted by mistake). The rest are only counted.
MAX_LINES_READ = 500
#: The judge is asked about each line, up to memory_merge.NEAREST times, on the user's fast model: at this pace, and
#: only for this long before the card shows what's done. No answer is no match, as everywhere MEM1 asks.
JUDGE_AT_ONCE = 6
JUDGE_BUDGET_S = 12.0

_BULLET = re.compile(r"^(?:[-*•‣·]|\d+[.)])(?:\s+|$)")
_DATE = re.compile(r"^\[?\d{4}-\d{2}-\d{2}\]?\s*[-–—:]?\s*")
_NOT_A_LINE = re.compile(r"^(?:```|#{1,6}\s)")


def split(text: str | None) -> list[tuple[str, bool]]:
    """One (line, offered) per candidate, without its bullet or date. Fences, headings, a line introducing a list
    ("Here is what I know:") and a line with no letter or number aren't candidates. Beside a list, a plain line is the
    asking and not a memory, and so is a plain line alone, so a follow-up ("yes, import those") offers nothing. With no
    list and several lines, each is offered, the asking too if it's there: the card shows it, to untick."""
    lines = []
    for raw in (text or "").splitlines():
        raw = raw.strip()
        line = _DATE.sub("", _BULLET.sub("", raw)).strip()
        if any(ch.isalnum() for ch in line) and not _NOT_A_LINE.match(line) and not line.endswith((":", "：")):
            lines.append((line, line != raw))
    if any(listed for _, listed in lines):
        return lines
    return [(line, len(lines) > 1) for line, _ in lines]


async def _this_turns_message(conversation_id: str | None, message_id: int | None) -> str:
    """By the id the turn stored it under: a steer is a newer row, and a resumed task has no message of its own."""
    async with db_session.AsyncSessionLocal() as db:
        return await db.scalar(select(ArslanMessage.content).where(
            ArslanMessage.id == message_id, ArslanMessage.conversation_id == conversation_id,
            ArslanMessage.role == "user")) or ""


async def _out_of_learning(conversation_id: str, message_id: int) -> None:
    """Post-turn learning reads only what comes after this message, and skips its own turn (turn_facts.capture). Those
    before it were each read after their own turn."""
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(ConversationContext, conversation_id) or ConversationContext(id=conversation_id)
        row.learns_after_message_id = message_id
        db.add(row)
        await db.commit()


async def _sort(text: str, actor) -> tuple[list[dict], list[dict], int]:
    """(the lines it would keep, the rest with why, how many weren't read). A line holding a key isn't shown again."""
    entries: list[dict] = []
    left_out: list[dict] = []
    seen: set[str] = set()
    scope = MemoryScope(kind="global")
    lines = split(text)
    for index, (raw, offered) in enumerate(lines):
        if len(entries) >= MAX_ENTRIES or index >= MAX_LINES_READ:
            return entries, left_out, len(lines) - index
        line = untrusted.clean_body(raw).strip()
        same = normalized_memory(line)
        if same in seen:
            continue
        seen.add(same)
        if contains_credential(line):
            left_out.append({"text": None, "reason": "credential"})
            continue
        if len(line) > turn_facts.MAX_FACT_CHARS:
            left_out.append({"text": f"{line[:120]}…", "reason": "too_long"})
            continue
        if not offered:
            left_out.append({"text": line, "reason": "beside_the_list"})
            continue
        why = turn_facts.why_not_kept(line)
        if why:
            left_out.append({"text": line, "reason": why})
            continue
        async with repository() as repo:
            known = await repo.already(MemoryWrite(content=line, kind="preference", scope=scope), actor)
        if known:
            left_out.append({"text": line, "reason": known})
        else:
            entries.append({"id": f"e{len(entries)}", "text": line, "ticked": True, "same_as": None})
    return entries, left_out, 0


async def _said_by(entry_id: str) -> str | None:
    async with db_session.AsyncSessionLocal() as db:
        return await db.scalar(select(MemoryRevision.content).join(
            MemoryEntry, MemoryEntry.current_revision_id == MemoryRevision.id).where(MemoryEntry.id == entry_id))


async def _mark_the_same(entries: list[dict], ctx) -> None:
    """Which lines say the same as a stored entry, as far as the judge answers within the budget."""
    gate = asyncio.Semaphore(JUDGE_AT_ONCE)
    scope = MemoryScope(kind="global")

    async def one(entry: dict) -> None:
        async with gate:
            match = await memory_merge.same_meaning(entry["text"], ctx=ctx, kind="preference", scope=scope,
                                                    core=None, sensitive=False)
            stored = await _said_by(match.id) if match else None
        if stored:
            entry.update(ticked=False, same_as=stored)

    tasks = [asyncio.create_task(one(entry)) for entry in entries]
    try:
        await asyncio.wait(tasks, timeout=JUDGE_BUDGET_S)
    finally:                                    # the budget's end or a Stop: no judge goes on. A failed one is no match.
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def propose(args: dict, *, conversation_id: str | None, ask) -> dict:
    """The model's `import_memories`. `args` names no text: it only says why."""
    ctx = pc.current()
    if ctx is None:
        return {"ok": False, "error": "memory_context_unavailable"}
    if ctx.no_learning or ctx.temporary:
        return {"ok": False, "error": "learning_disabled",
                "note": "This conversation keeps no memories, so nothing can be imported here. Say so."}
    from server.services import approvals, background_jobs, permissions
    why = untrusted.clean_name(args.get("why"), 300)
    # The ledger keeps that it asked and the model's reason; never the lines.
    request = permissions.Request(kind="capability", target="memory_import", title="Import memories?", detail=why)
    context = permissions.Context(conversation_id, job_id=background_jobs._inside_job.get())
    if ask is None:
        if permissions.current_asker() is None:
            await permissions.refuse_unattended(request, context)
        return {"ok": False, "not_saved": True,
                "note": "Nobody to ask here (a background job or a scheduled run), so nothing was read or stored. "
                        "Offer to import them when the user is in the conversation."}
    actor = ctx.actor("user")
    text = await _this_turns_message(conversation_id, ctx.source_message_id)
    entries, left_out, too_many = await _sort(text, actor)
    if not entries:
        return {"ok": False, "nothing_to_import": True, "left_out": len(left_out) + too_many,
                "note": "This message holds no lines to import. They have to be pasted in the same message that asks; "
                        "say so, or say why they were left out."}
    await _out_of_learning(conversation_id, ctx.source_message_id)     # before the judges: a Stop there ends the turn
    await _mark_the_same(entries, ctx)
    card = {"kind": KIND, "name": "memories", "why": why, "entries": entries, "left_out": left_out,
            "too_many": too_many, "lines": len(text.splitlines()), "keys": [], "folders": []}
    approvals.LAST_OUTCOME.set(None)          # only this card's own outcome may read as expired
    decision = await ask(card)
    await permissions.record_card_outcome(request, context, approved=bool(decision.get("approved")),
                                          expired=approvals.LAST_OUTCOME.get() == "expired")
    if not decision.get("approved"):
        outcome = approvals.LAST_OUTCOME.get() or "declined"
        return {"ok": False, "declined": True,
                "note": f"The user did not import them ({outcome}), and nothing was stored. Do not propose it again now."}
    kept = set(decision.get("kept") or [])
    saved = not_saved = 0
    for entry in entries:
        if entry["id"] not in kept:
            continue
        # On the card, read and kept: that's the user's yes for a sensitive line too. A cloud model is shown what
        # "Remember me" allows, as for a noticed fact (decide_write), and never a sensitive line.
        cloud = ctx.cloud_memory_effective and not sensitive_words(entry["text"])
        write = MemoryWrite(content=entry["text"], kind="preference", scope=MemoryScope(kind="global"),
                            use_policy="cloud_allowed" if cloud else "local_only", sensitive_acknowledged=True)
        try:
            async with repository() as repo:
                await repo.create(write, actor)
            saved += 1
        except Exception:  # noqa: BLE001 — the lines before it are in: the counts stay true, and the rest go on
            logger.warning("memory import: a kept line wasn't stored", exc_info=True)
            not_saved += 1
    return {"ok": True, "saved": saved, "not_saved": not_saved, "left_out": len(left_out) + too_many,
            "note": "Tell the user how many were saved (`saved`). They can edit or delete any of them in Memory."}
