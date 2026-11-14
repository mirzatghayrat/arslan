"""SIDE-1 (v0.1.64, docs/plans/0164/SIDE-side-chat.md): side chats, the backend.

A side chat is a conversation of its own, `kind="side"` (migration 0071's column), under the conversation it was branched
from (`parent_id`), at one of that conversation's messages (`branch_message_id`, migration 0099). Its id is minted here,
`side-` and a UUID (`phone_ids.SIDE_PREFIX`), so one with no row still reads as a side chat. Its messages are its own;
the window talks to it over the socket as to any conversation.

- What it reads: its parent up to the branch, then its own messages (`parent_part`, read first by
  `memory.assemble_working_context`). Nothing later in the parent, and nothing of its own reaches the parent: the
  parent's history, compaction, facts and search read only the parent's rows. It is never compacted itself
  (`memory.maybe_compact`): a long one drops its oldest parent messages first.
- Read-only (card, rule 2): it is shown, and may call, `TOOLS` only (`arslan._side_tools`), and no job starts in it
  (`sub_sessions.refusal`).
- Its settings are its parent's, read through it each turn (`sub_sessions._chain`). It reads memory as its parent
  does (the user's ruling, 2026-11-14) and writes none: learning is off, on its row and in `effective_settings` for
  any side chat whatever its row says, so every memory or lesson write refuses (`learning_disabled`). No route sets
  anything on it (`side_chat_inherits`). It runs on its parent's model
  (`llm_factory`), and a local-only receipt of its parent counts as its own (`task_context.load`).
- The outside-content mark (card, rule 3): worked out once when it is made, and stored (`outside_at_start`). Every turn
  of one that started marked starts marked (`arslan._answer_dispatch`); a clean one is marked by what each turn reads.
- It is in no list of conversations (`phone_ids.in_list`), not on the phone (`sub_sessions.sub_ids`), and the whole
  app counts its work as its parent's (`sub_sessions.commanders`, `not_sub`). It goes with its parent
  (`sub_sessions.before_delete`), and alone only when the delete names it as one.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import func, or_, select, true

from server.db.companion_models import ConversationContext
from server.db.models import ArslanMessage, ArslanSummary, Run
from server.orchestrator import untrusted
from server.services import phone_ids, sub_sessions
from server.services.memory_history import eligible_messages

#: Card, rule 2: all a side chat is shown and may call. Reads are open and the defences are on writes and the network
#: (⓪Plan, 2026-11-14, as mainstream agents do), so the web is in: the parent's turns run these two with no card in any
#: mode. A list, not a trait: 23 tools say they read, `start_sub_session`'s door, the shared browser and Hands among
#: them. Each stays only while its traits say it reads (`arslan._side_tools`). None writes, runs a command, remembers,
#: schedules, starts work, asks a card of its own kind or reaches an MCP server.
TOOLS = frozenset({"read_file", "list_dir", "search_files", "web_search", "web_extract"})


class SideChatError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status, self.code = status, code


@dataclass(frozen=True)
class Part:
    """What a side chat reads of its parent: the newest summary that ends by the branch, and the messages after that
    summary up to the branch, as the parent's own turns read them (`eligible_messages`)."""
    summary: ArslanSummary | None
    messages: list[ArslanMessage]


async def _part(db, parent_id: str, branch: int) -> Part:
    summary = (await db.execute(select(ArslanSummary).where(
        ArslanSummary.conversation_id == parent_id, ArslanSummary.up_to_message_id <= branch)
        .order_by(ArslanSummary.id.desc()).limit(1))).scalars().first()
    messages = (await db.execute(eligible_messages(parent_id).where(
        ArslanMessage.id > (summary.up_to_message_id if summary else 0), ArslanMessage.id <= branch)
        .order_by(ArslanMessage.id))).scalars().all()
    return Part(summary, list(messages))


async def parent_part(db, conversation_id: str) -> Part | None:
    """A side chat's part of its parent, read before its own messages; None for any other conversation."""
    row = await db.get(ConversationContext, conversation_id)
    if row is None or row.kind != sub_sessions.SIDE:
        return None
    if not row.parent_id or row.branch_message_id is None:
        return Part(None, [])
    return await _part(db, row.parent_id, row.branch_message_id)


async def _started_marked(db, parent_id: str, branch: int) -> bool:
    """Card, rule 3: whether a side chat branched here starts as having read outside content. Clean only when every
    run of the parent up to the branch recorded that it took in none (`runs.read_outside` false; NULL is a run still
    going, one that crashed or one from before 0072, and counts as read) and nothing in the part it reads is framed as
    outside content (a background job's result, posted with no run of its own; a summary folding one in). Up to the
    branch: a run started by the branch's time, or one a message up to the branch names.

    Stored when the side chat is made, never worked out again: later, a run still going now could read clean, and a
    run purged since would. An error here makes no side chat at all."""
    at = await db.scalar(select(ArslanMessage.timestamp).where(ArslanMessage.id == branch))
    named = select(ArslanMessage.run_id).where(ArslanMessage.conversation_id == parent_id, ArslanMessage.id <= branch)
    unclean = await db.scalar(select(Run.id).where(
        Run.conversation_id == parent_id, or_(Run.read_outside.is_(None), Run.read_outside.is_(True)),
        or_(Run.started_at <= at if at is not None else true(), Run.id.in_(named))).limit(1))
    if unclean is not None:
        return True
    part = await _part(db, parent_id, branch)
    return untrusted.folds_outside([part.summary.summary if part.summary else "", *(m.content for m in part.messages)])


def _item(row: ConversationContext, message_count: int, last_at) -> dict:
    return {"conversation_id": row.id, "parent_id": row.parent_id, "branch_message_id": row.branch_message_id,
            "outside_at_start": row.outside_at_start is not False, "created_at": row.created_at.isoformat(),
            "message_count": message_count, "last_at": last_at.isoformat() if last_at else None}


async def create(db, parent_id: str, branch_message_id: int | None) -> dict:
    """POST /conversations/{id}/side-chats: a new side chat of `parent_id`, branched at `branch_message_id`, or with
    none at the newest message the parent would read itself (the window's "+"). Committed under the lock a delete
    takes (`sub_sessions.starting`): a delete of the parent either finds it or is found first. Refused (SideChatError):
    - 404 `not_found`: the parent was deleted;
    - 422 `side_chat_parent_kind`: the parent isn't an ordinary conversation: a quick question, a sub-session (⓪Plan,
      2026-11-14: no side chat of a sub-session) or a side chat;
    - 422 `side_chat_from_temporary`: the parent is temporary;
    - 422 `invalid_branch_message`: the branch isn't one of the parent's messages;
    - 409 `side_chat_nothing_to_read`: no branch, and the parent has no message to read."""
    async with sub_sessions.starting():
        parent = await db.get(ConversationContext, parent_id)
        if sub_sessions.is_deleted(parent_id, parent):
            raise SideChatError(404, "not_found")
        if phone_ids.kind_of(parent_id, parent.kind if parent else None) not in (None, "chat"):
            raise SideChatError(422, "side_chat_parent_kind")
        if parent is not None and parent.temporary:
            raise SideChatError(422, "side_chat_from_temporary")
        if branch_message_id is None:
            branch = await db.scalar(eligible_messages(parent_id).with_only_columns(ArslanMessage.id)
                                     .order_by(ArslanMessage.id.desc()).limit(1))
            if branch is None:
                raise SideChatError(409, "side_chat_nothing_to_read")
        else:
            branch = await db.scalar(select(ArslanMessage.id).where(
                ArslanMessage.id == branch_message_id, ArslanMessage.conversation_id == parent_id))
            if branch is None:
                raise SideChatError(422, "invalid_branch_message")
        if parent is None:
            # As `sub_sessions.create_child` does: an ordinary conversation has no row until a setting changes, and a
            # chain with a row missing fails closed (no memory), so the side chat would never read memory.
            parent = ConversationContext(id=parent_id)
            db.add(parent)
        row = ConversationContext(
            id=f"{phone_ids.SIDE_PREFIX}{uuid4()}", owner_id=parent.owner_id if parent else "local",
            kind=sub_sessions.SIDE, parent_id=parent_id, no_learning=True, branch_message_id=branch,
            outside_at_start=await _started_marked(db, parent_id, branch))
        db.add(row)
        await db.flush()
        made = _item(row, 0, None)
        await db.commit()
    return made


async def listing(db, parent_id: str) -> list[dict]:
    """GET /conversations/{id}/side-chats: its side chats, oldest first. Open or closed is the window's to remember
    (the user, 2026-11-11: a closed one comes back from Overview's "Side chats" list). 404 for a deleted parent."""
    if sub_sessions.is_deleted(parent_id, await db.get(ConversationContext, parent_id)):
        raise SideChatError(404, "not_found")
    rows = (await db.execute(select(ConversationContext).where(
        ConversationContext.parent_id == parent_id, ConversationContext.kind == sub_sessions.SIDE)
        .order_by(ConversationContext.created_at, ConversationContext.id))).scalars().all()
    said = {cid: (count, last) for cid, count, last in (await db.execute(
        select(ArslanMessage.conversation_id, func.count(ArslanMessage.id), func.max(ArslanMessage.timestamp))
        .where(ArslanMessage.conversation_id.in_([row.id for row in rows]))
        .group_by(ArslanMessage.conversation_id))).all()}
    return [_item(row, *said.get(row.id, (0, None))) for row in rows]


async def carries_outside(db, conversation_id: str) -> bool:
    """SIDE-2's seam (⓪Plan, 2026-11-14): "Bring back to main" puts a side chat's reply into the main input framed as a
    quote, and the main turn that sends it starts as having read outside content when this is true: the side chat
    started marked, or one of its runs took in outside content (NULL, a run still going, counts). No side chat's row
    counts as yes. Not called before SIDE-2."""
    row = await db.get(ConversationContext, conversation_id)
    if row is None or row.outside_at_start is not False:
        return True
    return await db.scalar(select(Run.id).where(Run.conversation_id == conversation_id, or_(
        Run.read_outside.is_(None), Run.read_outside.is_(True))).limit(1)) is not None
