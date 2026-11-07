"""SUB2 (v0.1.64, docs/plans/0164/SUB-sub-sessions.md): a sub-session's data. A sub-session is a real conversation with
`kind="sub"` and a parent; SUB3 is what starts them.

Its settings are read through its parents each time they are used, never copied once, so a parent that tightens later
reaches the child's next turn. `INHERITANCE` says how each column of ConversationContext behaves, and a test fails when
a column is added without a line here.

A chain that can't be read (a parent gone, a loop, more layers than exist) fails closed: no memory, no learning, none of
the permissions.

SUB3: `start` opens one and runs it as a background job of its own conversation (`background_jobs.start` with a
`parent_id`). Its cards are asked in the parent's conversation and answered for the sub-session
(`approvals.SubSessionAsker`); it is offered `TOOLS` only (`arslan.background_body`); one tree shares a spending limit,
read before each model request, that wraps a run up before it stops it (`check_tree_spend`). No tool table offers `start` yet: SUB5 adds `start_sub_session`
once the M64 bench passes on its branch.
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select

from arslan.execution_budget import BudgetExceeded
from server.db.companion_models import ConversationContext

#: A conversation, a sub-session, and the one layer below it.
MAX_DEPTH = 3
SUB = "sub"
#: SUB3 (card, rule 10): how many sub-sessions one conversation may start, by its layer (a commander, a sub-session),
#: and how many may be alive at once in one tree. The bench may move these numbers.
MAX_CHILDREN = {1: 4, 2: 2}
MAX_ALIVE = 6
#: SUB3 (the user, 2026-11-07): what one tree's sub-sessions may spend together is this many times the per-run dollar
#: cap (K4a, Settings → Advanced; $2 by default, so $6), besides each run's own cap. Read where that cap is read
#: (`settings_service.task_usd_cap`), so it follows it: no cap, no tree limit. Step and token limits are each run's.
TREE_CAP_MULTIPLIER = 3
#: SUB3 (card, rule 6): all a sub-session is offered. No browser (there is one, shared by every run), no Hands, no
#: desktop, no memory tools, no find_tools: those stay with the commander.
TOOLS = frozenset({"read_file", "list_dir", "search_files", "write_file", "edit_file", "run_command",
                   "web_search", "web_extract", "update_plan"})
_starting: asyncio.Lock | None = None

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


class TreeLimitReached(BudgetExceeded):
    """A sub-session's model request would go past its tree's spending limit. A budget stop like any other: the run
    records it and ends (out_of_budget); the job card says which limit (`stop`)."""

    def __init__(self, spent: float, limit: float):
        super().__init__(f"Execution budget exhausted: the sub-sessions' shared limit (${limit:.2f}).")
        self.stop = {"reason": "usd", "scope": "tree", "used": f"${max(spent, limit):.2f}", "limit": f"${limit:.2f}"}


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

    A parent with no row yet gets one (an ordinary conversation has none until a setting changes), so that a chain with
    a row missing can fail closed. Deleting a conversation keeps its row today, so a deleted parent isn't a missing one:
    removing the rows is SUB5's cascade."""
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


async def root_of(db, conversation_id: str) -> str:
    """The top of this conversation's chain, as far as it can be read."""
    row = await db.get(ConversationContext, conversation_id)
    top, steps = conversation_id, 1
    while row is not None and row.kind == SUB and row.parent_id and steps < MAX_DEPTH:
        top, steps = row.parent_id, steps + 1
        row = await db.get(ConversationContext, top)
    return top


async def start(parent_id: str, brief: str, *, outside_seen: bool) -> str:
    """SUB3: a new sub-session of `parent_id`, its brief stored as its first message, running as a background job;
    returns its id at once. Refused (SubSessionError) below the second layer (`sub_session_depth`), past a
    conversation's share of children (`sub_session_children`), past the sub-sessions alive in one tree
    (`sub_session_alive`), and from a temporary chain (`sub_session_from_temporary`).

    `outside_seen`: the starting turn read outside content. The brief is then stored and given to the model framed as
    outside content, and every turn of the job starts as having read some (`untrusted.carried`). Either way the brief
    is not the user's words: the job drops what the user asked to save (`background_jobs._execute`)."""
    from server.db import session as db_session
    from server.orchestrator import memory, untrusted
    from server.services import background_jobs
    brief = brief.strip()
    if not brief:
        raise SubSessionError("sub_session_brief_required")
    global _starting
    if _starting is None:
        _starting = asyncio.Lock()
    async with _starting:            # two starts in one tree must not both pass the counts
        async with db_session.AsyncSessionLocal() as db:
            layer = await depth(db, parent_id)
            if layer >= MAX_DEPTH:
                raise SubSessionError("sub_session_depth")
            if len(await children(db, parent_id)) >= MAX_CHILDREN[layer]:
                raise SubSessionError("sub_session_children")
            members = set((await tree(db, await root_of(db, parent_id)))[1:])
            if sum(job.conversation_id in members for job in background_jobs.active()) >= MAX_ALIVE:
                raise SubSessionError("sub_session_alive")
            child = (await create_child(db, parent_id)).id
            await db.commit()
        framed = untrusted.wrap_external(brief) if outside_seen else None
        await memory.add_message(child, "user", framed or brief, display_content=brief if framed else None)
        await background_jobs.start(child, brief, [], outside_seen=outside_seen, parent_id=parent_id)
    return child


def _usd(snapshot) -> float:
    spent = ((snapshot or {}).get("spend") or {}).get("usd") if isinstance(snapshot, dict) else None
    ok = isinstance(spent, (int, float)) and not isinstance(spent, bool) and math.isfinite(spent) and spent > 0
    return float(spent) if ok else 0.0


async def tree_spend(db, conversation_ids) -> float:
    """What the runs in these conversations spent (card, SUB3): each task's latest budget snapshot (saved before every
    model request and around every tool, so it survives a restart), plus each finished run no task holds
    (`runs.execution_budget`)."""
    from server.db.models import Run
    from server.db.task_models import CompanionTask, TaskAttempt
    ids = list(conversation_ids)
    if not ids:
        return 0.0
    tasks = (await db.execute(select(CompanionTask.id, CompanionTask.budget)
                              .where(CompanionTask.conversation_id.in_(ids)))).all()
    held = {run for (run_ids,) in (await db.execute(select(TaskAttempt.run_ids).where(
        TaskAttempt.task_id.in_([task_id for task_id, _ in tasks])))).all() for run in run_ids or ()}
    runs = (await db.execute(select(Run.id, Run.execution_budget).where(
        Run.conversation_id.in_(ids), Run.ended_at.is_not(None)))).all()
    return sum(_usd(budget) for _, budget in tasks) + sum(_usd(budget) for run_id, budget in runs if run_id not in held)


async def check_tree_spend(conversation_id: str) -> None:
    """Before a sub-session's model request, with the request's own snapshot saved: stop at the tree's limit,
    TREE_CAP_MULTIPLIER times the per-run dollar cap as `settings_service.task_usd_cap` reads it (None: no cap, so no
    tree limit either). The tree is every sub-session under the same commander; the commander's own turns are not in
    it (they are the user's conversation, and a long one would stop every sub-session it starts). SUB4 adds the
    commander's summary turn.

    Completion first, as with the run's own cap: what the rest of the tree spent goes into the run's budget
    (`Budget.shared_usd`), so the run wraps up at limit / HARD_OVER_SOFT through `soft_reached` (the tool loop's "Work
    budget nearly used" step, the same as for its own cap) and is stopped here at the limit only if it doesn't."""
    from arslan.execution_budget import current
    from server.db import session as db_session
    from server.services import settings_service
    budget = current()
    async with db_session.AsyncSessionLocal() as db:
        usd_cap = await settings_service.task_usd_cap(db)
        if usd_cap is None:
            if budget is not None:
                budget.shared_usd = None
            return
        limit = TREE_CAP_MULTIPLIER * usd_cap
        spent = await tree_spend(db, (await tree(db, await root_of(db, conversation_id)))[1:])
    if budget is not None:          # its own spend is in `spent` already: the snapshot was saved just before
        budget.shared_usd = (max(0.0, spent - budget.usd), limit)
    if spent >= limit:
        raise TreeLimitReached(spent, limit)


def _reset_for_tests() -> None:
    global _starting
    _starting = None


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
