"""S3b (v0.1.63): undo a turn's conversation: the turn, every later one, and the facts they taught
(card S3; ⓪Plan's answers in the S3b plan). Its files are S3a's (`checkpoints.restore_files`).

- **The turn** is found from its reply (role arslan, `run_id`); it starts at the last user message
  before that reply. A turn with no reply (a choice card's answer) cannot be undone this way.
- **What goes:** every message of the conversation from that user message on (this turn and every
  later one: the confirm box says how many turns, ⓪Plan's Q2); the recap's `memory` events from then
  on (turn_facts' line, scoped to this conversation and that kind, Q5); and the "for this task" grants
  of the tasks those turns ran. An ended task drops its own, but a delete that failed would outlive the
  turn.
- **Facts, narrowly** (`MemoryRepository.forget_turns`): an entry whose first source is a removed turn
  is deleted; an older entry a removed turn only re-confirmed keeps all but that turn's source (Q4).
  Never: a tombstone of the fact's text (undo is not Forget: the same fact learnt elsewhere is saved),
  a whole-conversation suppression, wiped summaries, cleared run prompts. For each entry taken back, the
  removed turns' messages and runs are suppressed as its sources, so a writer still holding one cannot
  bring it back.
- **Refused:** `none` (no reply), `job` (a background job's result: it arrives after later turns, so
  the last user message before it is not its turn's; the turn that started the job can be undone),
  `already` (undone before), `summarised` (the user message is folded
  into the conversation's summary, which would go on saying it), `running` (a run, a turn, a background
  job, or a task those turns started is still going or paused), `finishing` (the post-turn job, which
  saves facts, has not ended after FINISH_WAIT_S; ⓪Plan's answer to the S3 plan's Q5).
- **The turn clock** (`memory.user_turn_count`, which ages temporary grants) never runs backwards: the
  undo records how many user turns it removed in a `turn_undone` event (also what `already` reads), and
  the clock adds them (Q6).
- **Ids** are never handed out again (migration 0069): the phone's seenUpTo, the window's resume and a
  summary's up_to_message_id stay right. A phone shows the undone turn until it reads the history again
  (§8; a re-read signal is on iOS's v1.1 list, Q3).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import delete, func, select, text

from server.db import session as db_session
from server.db.models import ArslanMessage, ArslanSummary, CompanionTask, ConversationEvent, PermissionGrant

FINISH_WAIT_S = 5.0
UNDONE = "turn_undone"                      # the event that records an undo
_ENDED = frozenset({"succeeded", "failed", "cancelled"})


class Refused(Exception):
    """`code`: none, job, already, summarised, running, finishing (the module docstring says when)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class _Turn:
    run_id: int
    conversation_id: str
    first: int                              # the turn's user message
    users: list[int]                        # the user messages that go (the first, then later turns')
    runs: set[int]                          # the runs whose replies go
    messages: int
    tasks: dict[str, str]                   # the tasks those turns ran: id -> phase


async def _find(db, run_id: int) -> _Turn:
    reply = await db.scalar(select(ArslanMessage).where(
        ArslanMessage.run_id == run_id, ArslanMessage.role == "arslan").order_by(ArslanMessage.id).limit(1))
    if reply is None:
        undone = await db.scalar(select(ConversationEvent.id).where(
            ConversationEvent.kind == UNDONE, func.json_extract(ConversationEvent.ref, "$.run_id") == run_id).limit(1))
        raise Refused("already" if undone else "none")
    if reply.job_outcome is not None:
        raise Refused("job")                # a job's result came after later turns: undo the turn that started it
    cid = reply.conversation_id
    first = await db.scalar(select(ArslanMessage).where(
        ArslanMessage.conversation_id == cid, ArslanMessage.role == "user", ArslanMessage.id < reply.id,
    ).order_by(ArslanMessage.id.desc()).limit(1))
    if first is None:
        raise Refused("none")
    folded = await db.scalar(select(func.max(ArslanSummary.up_to_message_id)).where(
        ArslanSummary.conversation_id == cid))
    if folded is not None and folded >= first.id:
        raise Refused("summarised")
    rows = (await db.execute(select(ArslanMessage.id, ArslanMessage.role, ArslanMessage.run_id).where(
        ArslanMessage.conversation_id == cid, ArslanMessage.id >= first.id))).all()
    runs = {row.run_id for row in rows if row.run_id is not None} | {run_id}
    # A turn's task starts just before its message is stored: found by its runs; a task started after
    # the first message that has no run yet, by its time.
    holders = ", ".join(str(int(r)) for r in runs)
    linked = (await db.execute(text(
        "SELECT DISTINCT t.id, t.phase FROM companion_tasks t JOIN task_attempts a ON a.task_id = t.id, "
        f"json_each(a.run_ids) j WHERE t.conversation_id = :cid AND j.value IN ({holders})"), {"cid": cid})).all()
    started = (await db.execute(select(CompanionTask.id, CompanionTask.phase).where(
        CompanionTask.conversation_id == cid, CompanionTask.created_at >= first.timestamp))).all()
    return _Turn(run_id=run_id, conversation_id=cid, first=first.id,
                 users=[row.id for row in rows if row.role == "user"], runs=runs, messages=len(rows),
                 tasks={task_id: phase for task_id, phase in (*linked, *started)})


def _busy(turn: _Turn, *, holding_lock: bool = False) -> None:
    from server.services import background_jobs, run_registry
    from server.ws import arslan as ws_arslan
    cid = turn.conversation_id
    lock = ws_arslan._turn_locks.get(cid)
    if run_registry.active_for(cid) or (not holding_lock and lock is not None and lock.locked()) \
            or any(job.phase != "finished" for job in background_jobs.jobs_for(cid)) \
            or any(phase not in _ENDED for phase in turn.tasks.values()):
        raise Refused("running")


def _post_turn_job(conversation_id: str) -> asyncio.Task | None:
    """The post-turn job (facts, compaction) still going for this conversation in this loop, if any."""
    from server.orchestrator import arslan
    job = arslan._after_turn_tail.get(conversation_id)
    if job is None or job.done() or job.get_loop() is not asyncio.get_running_loop():
        return None
    return job


async def preview(run_id: int) -> dict:
    """What GET /runs/{id}/checkpoint says about the conversation: whether it can be undone (or why not),
    how many messages and later turns go, and how many facts."""
    from server.services.memory_repository import MemoryRepository
    try:
        async with db_session.AsyncSessionLocal() as db:
            turn = await _find(db, int(run_id))
            _busy(turn)
            if _post_turn_job(turn.conversation_id) is not None:
                raise Refused("finishing")
            facts = len((await MemoryRepository(db).turn_entries(set(turn.users), turn.runs))[0])
    except Refused as exc:
        return {"conversation": False, "reason": exc.code}
    return {"conversation": True, "reason": None, "messages_after": turn.messages,
            "later_turns": len(turn.users) - 1, "facts": facts}


async def undo(run_id: int, *, first=None) -> dict:
    """Take the turn back (the module docstring says what that covers). Raises Refused.

    `first` (POST "both": putting the files back) is awaited after every check passed, under the turn lock,
    before the conversation goes; what it raises stops the undo with nothing taken back, and what it
    returns is the result's `files`."""
    from server.ws import arslan as ws_arslan
    run_id = int(run_id)
    async with db_session.AsyncSessionLocal() as db:
        turn = await _find(db, run_id)
    _busy(turn)
    job = _post_turn_job(turn.conversation_id)
    if job is not None:
        try:
            await asyncio.wait_for(asyncio.shield(job), FINISH_WAIT_S)
        except TimeoutError:
            raise Refused("finishing") from None
        except Exception:  # noqa: BLE001 — the job's own failure is logged where it happens
            pass
    lock = ws_arslan._turn_lock(turn.conversation_id)
    if lock.locked():
        raise Refused("running")
    async with lock:                        # no turn starts in this conversation while it is taken back
        async with db_session.AsyncSessionLocal() as db:
            turn = await _find(db, run_id)
        _busy(turn, holding_lock=True)
        if _post_turn_job(turn.conversation_id) is not None:
            raise Refused("finishing")
        files = await first() if first is not None else None
        async with db_session.AsyncSessionLocal() as db:
            out = await _take_back(db, await _find(db, run_id))
            await db.commit()
    return out if first is None else {**out, "files": files}


async def _take_back(db, turn: _Turn) -> dict:
    from server.services.memory_repository import MemoryRepository
    cid = turn.conversation_id
    facts = await MemoryRepository(db).forget_turns(set(turn.users), turn.runs)
    first_at = await db.scalar(select(ArslanMessage.timestamp).where(ArslanMessage.id == turn.first))
    await db.execute(delete(ConversationEvent).where(
        ConversationEvent.conversation_id == cid, ConversationEvent.kind == "memory",
        ConversationEvent.created_at >= first_at))
    if turn.tasks:
        await db.execute(delete(PermissionGrant).where(
            PermissionGrant.conversation_id == cid, PermissionGrant.task_id.in_(list(turn.tasks))))
    await db.execute(delete(ArslanMessage).where(
        ArslanMessage.conversation_id == cid, ArslanMessage.id >= turn.first))
    db.add(ConversationEvent(conversation_id=cid, kind=UNDONE, summary="", ref={
        "run_id": turn.run_id, "user_turns": len(turn.users), "messages": turn.messages, "facts": facts}))
    return {"run_id": turn.run_id, "conversation_id": cid, "messages": turn.messages,
            "later_turns": len(turn.users) - 1, "facts": facts}


def undone_turns_clause(conversation_id: str):
    """For `memory.user_turn_count`: the user turns undone in this conversation."""
    return select(func.coalesce(func.sum(func.json_extract(ConversationEvent.ref, "$.user_turns")), 0)).where(
        ConversationEvent.conversation_id == conversation_id, ConversationEvent.kind == UNDONE)

