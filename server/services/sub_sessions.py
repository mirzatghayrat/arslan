"""SUB2 (v0.1.64, docs/plans/0164/SUB-sub-sessions.md): a sub-session's data. A sub-session is a real conversation with
`kind="sub"` and a parent; SUB3 is what starts them.

Its settings are read through its parents each time they are used, never copied once, so a parent that tightens later
reaches the child's next turn. `INHERITANCE` says how each column of ConversationContext behaves, and a test fails when
a column is added without a line here.

A chain that can't be read (a parent gone, a loop, more layers than exist) fails closed: no memory, no learning, none of
the permissions.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select

from server.db.companion_models import ConversationContext

#: A conversation, a sub-session, and the one layer below it.
MAX_DEPTH = 3
SUB = "sub"

#: How a child reads each column. strictest_on: on if anyone along the chain has it on. strictest_off: on only if
#: everyone along the chain has it on. parent: the top of the chain's value. own: the child's own.
INHERITANCE: dict[str, str] = {
    "id": "own",
    "owner_id": "parent",
    "project_id": "parent",
    "no_memory": "strictest_on",
    "no_learning": "strictest_on",
    "temporary": "strictest_on",
    "cloud_memory_allowed": "strictest_off",
    "allow_sensitive": "strictest_off",
    "kind": "own",
    "parent_id": "own",
    "learns_after_message_id": "own",
    "pinned": "own",
    "version": "own",
    "created_at": "own",
    "updated_at": "own",
}
_ON = tuple(name for name, how in INHERITANCE.items() if how == "strictest_on")
_OFF = tuple(name for name, how in INHERITANCE.items() if how == "strictest_off")


class SubSessionError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class EffectiveSettings:
    project_id: str | None
    no_memory: bool
    no_learning: bool
    temporary: bool
    cloud_memory_allowed: bool
    allow_sensitive: bool


async def _chain(db, row: ConversationContext) -> tuple[list[ConversationContext], bool]:
    """`row` and its parents, nearest first, and whether the chain is whole."""
    chain = [row]
    while chain[-1].kind == SUB:
        parent_id = chain[-1].parent_id
        if not parent_id or parent_id in {r.id for r in chain} or len(chain) >= MAX_DEPTH:
            return chain, False
        parent = await db.get(ConversationContext, parent_id)
        if parent is None:
            return chain, False
        chain.append(parent)
    return chain, True


async def effective_settings(db, row: ConversationContext) -> EffectiveSettings:
    """What this conversation's settings are right now. An ordinary conversation reads its own row."""
    chain, whole = await _chain(db, row)
    on = {name: any(bool(getattr(r, name)) for r in chain) for name in _ON}
    off = {name: all(bool(getattr(r, name)) for r in chain) for name in _OFF}
    if row.kind == SUB:
        on["no_learning"] = True                # a sub-session never learns, whatever its row says
    if not whole:
        on["no_memory"] = True
        off = dict.fromkeys(_OFF, False)
    return EffectiveSettings(project_id=chain[-1].project_id, **on, **off)


async def depth(db, conversation_id: str) -> int:
    """Which layer this conversation is on, 1 at the top, counting at most MAX_DEPTH."""
    row = await db.get(ConversationContext, conversation_id)
    layer = 1
    while row is not None and row.kind == SUB and row.parent_id and layer < MAX_DEPTH:
        row = await db.get(ConversationContext, row.parent_id)
        layer += 1
    return layer


async def create_child(db, parent_id: str, child_id: str | None = None) -> ConversationContext:
    """A new sub-session of `parent_id`; the caller commits. It starts with what its parent allows right now, and its
    parent can take that back later. Its name comes from its first message, as every conversation's does.

    A parent with no row yet gets one (an ordinary conversation has none until a setting changes), so that a missing
    parent always means a deleted one."""
    parent = await db.get(ConversationContext, parent_id)
    if parent is None:
        parent = ConversationContext(id=parent_id)
        db.add(parent)
        await db.flush()
    effective = await effective_settings(db, parent)
    if effective.temporary:
        raise SubSessionError("sub_session_from_temporary")
    if await depth(db, parent_id) >= MAX_DEPTH:
        raise SubSessionError("sub_session_depth")
    child = ConversationContext(
        id=child_id or f"sub-{uuid4()}", owner_id=parent.owner_id, kind=SUB, parent_id=parent_id,
        project_id=effective.project_id, no_learning=True,
        cloud_memory_allowed=effective.cloud_memory_allowed, allow_sensitive=effective.allow_sensitive)
    db.add(child)
    await db.flush()
    return child


async def children(db, parent_id: str) -> list[str]:
    return list((await db.execute(select(ConversationContext.id).where(
        ConversationContext.parent_id == parent_id, ConversationContext.kind == SUB))).scalars())


async def tree(db, root_id: str) -> list[str]:
    """`root_id` and everything below it."""
    found, queue = [root_id], [root_id]
    while queue:
        for child in await children(db, queue.pop()):
            if child not in found:
                found.append(child)
                queue.append(child)
    return found


async def sub_ids(db, ids: list[str]) -> set[str]:
    """Which of these conversations are sub-sessions, for the lists that start from something other than
    conversation_list (running jobs)."""
    if not ids:
        return set()
    return set((await db.execute(select(ConversationContext.id).where(
        ConversationContext.id.in_(ids), ConversationContext.kind == SUB))).scalars())


async def looser_than_chain(db, row: ConversationContext, values: dict) -> bool:
    """Whether these settings for a sub-session are looser than its chain allows. Stricter is always fine."""
    parent = await db.get(ConversationContext, row.parent_id) if row.parent_id else None
    if parent is None:
        return True
    chain = await effective_settings(db, parent)
    if not values.get("no_learning") or values.get("project_id") != chain.project_id:
        return True
    return (any(getattr(chain, name) and not values.get(name) for name in _ON)
            or any(values.get(name) and not getattr(chain, name) for name in _OFF))
