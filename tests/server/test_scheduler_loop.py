"""S3-M4 Task 2: scheduler execution loop — headless dispatch, kind='scheduled',
corpus isolation.

Contract under test:
  - tick() iterates due tasks: overlap → skipped_overlap row (ONE per due period,
    review I3 — next_due advances on skip); otherwise a SUPERVISED _fire;
  - _fire inserts the in-flight scheduled_task_run row FIRST, dispatches headless
    (RunRecorder kind='scheduled' + dispatcher.dispatch — deliberately NOT
    arslan._dispatch_spawn: no roster join, no routing announcement), finalizes the
    recorder with usage detail, records the ok/error outcome against the EXPLICIT
    row id (review S6) and logs a best-effort conversation_events 'scheduled_fire';
  - kind='scheduled' persists on the runs row END-TO-END (finalize must preserve a
    non-live kind set at start());
  - D2 corpus isolation (structural): a scored kind='scheduled' run never enters
    replay_set's corpus nor the evolution watcher's new-run trigger count;
  - a deleted spawn (FK SET NULL / dangling id) is a clean outcome='error'
    reason='spawn 已删除' (review S8), never an unhandled supervisor crash;
  - watch_loop sweeps orphaned in-flight rows at entry (review I2), ticks every
    `interval`, and stop_event interrupts the sleep; start()/stop() are idempotent.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from arslan.llm import usage_sink
from server.db import session as db_session
from server.db.models import (
    ArslanMessage,
    Base,
    ConversationEvent,
    Run,
    RunEvaluation,
    ScheduledTask,
    ScheduledTaskRun,
    Spawn,
)
from server.services import (
    evolution_watcher,
    replay_set,
    run_recorder,
    run_registry,
    scheduler,
)


@pytest.fixture
async def memdb(tmp_path, monkeypatch):
    """File-backed like the watcher tests (wdb): supervised fires run CONCURRENTLY,
    each with its own session — a shared :memory: StaticPool connection would
    interleave their transactions."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 's.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    # No judge in these tests: finalize must not fire real scoring tasks.
    monkeypatch.setattr(run_recorder, "schedule_scoring", lambda run_id: None)
    yield Session
    for t in list(scheduler._tasks):
        t.cancel()
    scheduler._tasks.clear()
    await engine.dispose()


async def _seed_spawn(Session, name: str = "S") -> int:
    async with Session() as db:
        spawn = Spawn(name=name, domain_category="general", system_prompt="sp")
        db.add(spawn)
        await db.commit()
        await db.refresh(spawn)
        return spawn.id


async def _seed_task(Session, **overrides) -> int:
    fields = dict(name="早报", prompt="做每日早报", schedule_kind="interval",
                  interval_s=3600, enabled=True, consecutive_failures=0,
                  next_due_at=datetime.utcnow() - timedelta(minutes=1))
    fields.update(overrides)
    async with Session() as db:
        task = ScheduledTask(**fields)
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task.id


async def _drain() -> None:
    """Await every supervised _fire task the tick just launched."""
    for _ in range(50):
        tasks = [t for t in scheduler._tasks if not t.done()]
        if not tasks:
            break
        await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.sleep(0)


async def _task_runs(Session, task_id: int) -> list[ScheduledTaskRun]:
    async with Session() as db:
        return list((await db.execute(
            select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == task_id)
            .order_by(ScheduledTaskRun.id))).scalars().all())


def _ok_dispatch(calls: list, output: str = "今日早报内容"):
    async def fake_dispatch(conversation_id, **kwargs):
        calls.append((conversation_id, kwargs))
        kwargs["on_chunk"]("今日")
        kwargs["on_event"]({"type": "tool_call", "tool": "web_search", "args_summary": "{}"})
        kwargs["on_event"]({"type": "tool_result", "tool": "web_search", "ok": True,
                            "summary": "1 result"})
        return {"full_output": output, "spawn_name": "S", "summary_message_id": None,
                "assistant_message_id": None, "escalation": None, "artifact": None}
    return fake_dispatch


# ---------------------------------------------------------------------------
# tick → _fire ok path
# ---------------------------------------------------------------------------


async def _wait_until(predicate, why: str, *, timeout: float = 5.0) -> None:
    """Poll until `predicate()` holds, or fail saying what never happened.

    Deliberately not `asyncio.sleep(<a guess>)`: a fixed wait encodes an
    assumption about how fast the machine is, passes on a quiet laptop, and goes
    red on a busy CI runner while the code under test is fine. The timeout is
    generous because it only bounds the FAILURE case — a healthy run leaves as
    soon as the condition is true.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(why)


async def test_tick_fires_due_task_end_to_end_ok(memdb, monkeypatch):
    spawn_id = await _seed_spawn(memdb)
    task_id = await _seed_task(memdb, spawn_id=spawn_id, conversation_id=None)
    cid = f"scheduled-{task_id}"
    calls: list = []
    monkeypatch.setattr(scheduler.dispatcher, "dispatch", _ok_dispatch(calls))
    frames: list[dict] = []
    run_registry.attach_sink(cid, frames.append)
    try:
        await scheduler.tick()
        await _drain()
    finally:
        run_registry.detach_sink(cid, frames.append)

    # dispatch was called headless with the right seam args
    assert len(calls) == 1
    got_cid, kwargs = calls[0]
    assert got_cid == cid                       # dedicated conversation when unset
    assert kwargs["spawn_id"] == spawn_id
    assert kwargs["task_brief"] == "做每日早报"
    assert kwargs["run_id"] is not None

    # the run row persists kind='scheduled' END-TO-END (start + finalize)
    async with memdb() as db:
        run = await db.get(Run, kwargs["run_id"])
    assert run is not None
    assert run.kind == "scheduled"
    assert run.status == "recorded"
    assert run.epoch == 1
    assert run.conversation_id == cid
    assert run.user_message == "做每日早报"
    assert run.spawn_name == "S"

    # outcome row finalized ok and linked to the run
    rows = await _task_runs(memdb, task_id)
    assert len(rows) == 1
    assert rows[0].outcome == "ok"
    assert rows[0].run_id == kwargs["run_id"]
    assert rows[0].finished_at is not None

    # task state advanced
    async with memdb() as db:
        task = await db.get(ScheduledTask, task_id)
    assert task.consecutive_failures == 0
    assert task.last_fired_at is not None
    assert task.next_due_at == task.last_fired_at + timedelta(seconds=3600)

    # best-effort conversation_events timeline entry
    async with memdb() as db:
        events = list((await db.execute(
            select(ConversationEvent).where(
                ConversationEvent.conversation_id == cid))).scalars().all())
    assert [e.kind for e in events] == ["scheduled_fire"]
    assert events[0].ref["task_id"] == task_id
    assert events[0].ref["run_id"] == kwargs["run_id"]

    # M2 fan-out: an attached (online) sink saw the live stream
    kinds = [f["type"] for f in frames]
    assert "stream_start" in kinds
    assert "stream_chunk" in kinds
    assert "stream_end" in kinds


async def test_stream_end_carries_usage_payload(memdb, monkeypatch):
    """Task-2 review I2(b) — 成本只可见: the scheduled fire's terminal stream_end
    must carry the SAME M3 usage payload the live path emits, built inside the
    collecting scope from the snapshot finalize persists (frame chip and Run row
    can never disagree). Price anchors: claude-sonnet-5 = (3, 15) USD/MTok."""
    spawn_id = await _seed_spawn(memdb)
    task_id = await _seed_task(memdb, spawn_id=spawn_id, conversation_id=None)
    cid = f"scheduled-{task_id}"

    async def reporting_dispatch(conversation_id, **kwargs):
        # Mirror LLMAdapter's choke point: structured detail + a total token count
        # into the ACTIVE usage sink of the fire's collecting scope.
        usage_sink.report_detail(tokens_in=1000, tokens_out=100,
                                 model="claude-sonnet-5-20260101", provider="anthropic")
        usage_sink.report(1100)
        return {"full_output": "o", "spawn_name": "S", "summary_message_id": None,
                "assistant_message_id": None, "escalation": None, "artifact": None}
    monkeypatch.setattr(scheduler.dispatcher, "dispatch", reporting_dispatch)

    frames: list[dict] = []
    run_registry.attach_sink(cid, frames.append)
    try:
        await scheduler.tick()
        await _drain()
    finally:
        run_registry.detach_sink(cid, frames.append)

    ends = [f for f in frames if f["type"] == "stream_end"]
    assert len(ends) == 1
    usage = ends[0]["usage"]
    assert usage["tokens_in"] == 1000
    assert usage["tokens_out"] == 100
    assert usage["tokens_total"] == 1100
    assert usage["estimated"] is False
    assert usage["usd"] == pytest.approx(1000 / 1e6 * 3 + 100 / 1e6 * 15)


async def test_fire_lands_in_the_configured_conversation(memdb, monkeypatch):
    spawn_id = await _seed_spawn(memdb)
    await _seed_task(memdb, spawn_id=spawn_id, conversation_id="c-42")
    calls: list = []
    monkeypatch.setattr(scheduler.dispatcher, "dispatch", _ok_dispatch(calls))
    await scheduler.tick()
    await _drain()
    assert len(calls) == 1
    assert calls[0][0] == "c-42"


# ---------------------------------------------------------------------------
# error path
# ---------------------------------------------------------------------------

async def test_dispatch_error_records_error_outcome_and_failure_count(memdb, monkeypatch):
    spawn_id = await _seed_spawn(memdb)
    task_id = await _seed_task(memdb, spawn_id=spawn_id)

    async def broken_dispatch(conversation_id, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(scheduler.dispatcher, "dispatch", broken_dispatch)

    await scheduler.tick()
    await _drain()

    rows = await _task_runs(memdb, task_id)
    assert len(rows) == 1
    assert rows[0].outcome == "error"
    assert "boom" in rows[0].reason
    assert rows[0].run_id is not None    # the failed Run is linked for diagnosis

    async with memdb() as db:
        task = await db.get(ScheduledTask, task_id)
        run = await db.get(Run, rows[0].run_id)
    assert task.consecutive_failures == 1
    assert task.enabled is True
    # recorder finalized with error fields, kind preserved (mirrors _dispatch_spawn)
    assert run.status == "recorded"
    assert run.kind == "scheduled"
    assert run.error_kind == "RuntimeError"
    assert "boom" in (run.error_text or "")


async def test_spawn_deleted_is_clean_error_outcome(memdb, monkeypatch):
    """Review S8: spawn_id None (ondelete SET NULL) or dangling → outcome='error'
    reason='spawn 已删除'; self-heals via the 3-fail auto-pause, never a crash."""
    async def unreachable_dispatch(conversation_id, **kwargs):
        raise AssertionError("dispatch must not run without a spawn")
    monkeypatch.setattr(scheduler.dispatcher, "dispatch", unreachable_dispatch)

    task_id = await _seed_task(memdb, spawn_id=None)
    dangling_id = await _seed_task(memdb, spawn_id=99999)

    await scheduler.tick()
    await _drain()

    for tid in (task_id, dangling_id):
        rows = await _task_runs(memdb, tid)
        assert len(rows) == 1
        assert rows[0].outcome == "error"
        assert rows[0].reason == "spawn 已删除"
        assert rows[0].run_id is None    # no Run row was ever started
    async with memdb() as db:
        assert (await db.execute(select(Run))).scalars().all() == []


# ---------------------------------------------------------------------------
# Task-2 review I3: scheduled fires are REGISTERED runs — cancellable, reattachable
# ---------------------------------------------------------------------------

def _hanging_dispatch(started: asyncio.Event, release: asyncio.Event,
                      output: str = "今日早报内容"):
    async def fake_dispatch(conversation_id, **kwargs):
        started.set()
        await release.wait()
        return {"full_output": output, "spawn_name": "S", "summary_message_id": None,
                "assistant_message_id": None, "escalation": None, "artifact": None}
    return fake_dispatch


async def test_cancel_mid_fire_finalizes_cancelled_without_counting_failure(
        memdb, monkeypatch):
    """Task-2 review I3: the fire's dispatch runs as a run_registry-registered task,
    so POST /runs/{id}/cancel (run_registry.cancel) reaches it mid-fire; the Run
    finalizes status='cancelled', the outcome row is error/'cancelled by user'
    WITHOUT advancing the 3-fail auto-pause counter, the single-flight gate is
    released, and the registration is cleaned up."""
    spawn_id = await _seed_spawn(memdb)
    task_id = await _seed_task(memdb, spawn_id=spawn_id, conversation_id=None,
                               consecutive_failures=2)   # 1 counted failure from pausing
    cid = f"scheduled-{task_id}"
    started, release = asyncio.Event(), asyncio.Event()   # release never set: hung fire
    monkeypatch.setattr(scheduler.dispatcher, "dispatch",
                        _hanging_dispatch(started, release))

    await scheduler.tick()
    await asyncio.wait_for(started.wait(), 2)

    # Mid-fire the run is registered WITH its recorder: a reattaching WS can replay
    # the journal frames, and the cancel seam resolves the task.
    snapshots = run_registry.journal_snapshots(cid)
    assert len(snapshots) == 1
    run_id, events = snapshots[0]
    assert any(e["type"] == "stream_start" for e in events)
    assert run_registry.cancel(run_id) is True

    await _drain()

    async with memdb() as db:
        run = await db.get(Run, run_id)
        task = await db.get(ScheduledTask, task_id)
    assert run.status == "cancelled"                  # never scored, never corpus
    assert run.kind == "scheduled"
    rows = await _task_runs(memdb, task_id)
    assert len(rows) == 1
    assert rows[0].outcome == "error"
    assert rows[0].reason == "cancelled by user"
    assert rows[0].run_id == run_id
    assert task.consecutive_failures == 2             # cancel did NOT count
    assert task.enabled is True                       # and did NOT pause
    assert await scheduler.has_inflight(task_id) is False   # single-flight released
    assert run_registry.get(run_id) is None           # unregistered in finally


async def test_fire_registers_and_unregisters_run(memdb, monkeypatch):
    """The happy path also registers (WS reattach must see a mid-fire run) and
    unregisters once the fire completes."""
    spawn_id = await _seed_spawn(memdb)
    task_id = await _seed_task(memdb, spawn_id=spawn_id, conversation_id=None)
    cid = f"scheduled-{task_id}"
    started, release = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(scheduler.dispatcher, "dispatch",
                        _hanging_dispatch(started, release))

    await scheduler.tick()
    await asyncio.wait_for(started.wait(), 2)
    assert len(run_registry.active_for(cid)) == 1     # registered while in flight

    release.set()
    await _drain()
    assert run_registry.active_for(cid) == []         # unregistered after the fire
    rows = await _task_runs(memdb, task_id)
    assert [r.outcome for r in rows] == ["ok"]


# ---------------------------------------------------------------------------
# Task-2 review S4: next_due advances at FIRE time — long fires never look due
# ---------------------------------------------------------------------------

async def test_fire_spanning_ticks_records_zero_skip_rows(memdb, monkeypatch):
    """S4: a fire outliving one 60s tick must not leave the task looking due —
    next_due_at advances when the fire STARTS, so subsequent ticks during the
    same period record ZERO skipped_overlap rows."""
    spawn_id = await _seed_spawn(memdb)
    task_id = await _seed_task(memdb, spawn_id=spawn_id)
    started, release = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(scheduler.dispatcher, "dispatch",
                        _hanging_dispatch(started, release))

    await scheduler.tick()
    await asyncio.wait_for(started.wait(), 2)

    async with memdb() as db:
        task = await db.get(ScheduledTask, task_id)
    assert task.next_due_at > datetime.utcnow()       # period consumed at fire time

    await scheduler.tick()                            # "next 60s tick", still in flight
    await scheduler.tick()                            # and another
    rows = await _task_runs(memdb, task_id)
    assert [r.outcome for r in rows] == [None]        # in-flight row only, NO skips

    release.set()
    await _drain()
    rows = await _task_runs(memdb, task_id)
    assert [r.outcome for r in rows] == ["ok"]


async def test_second_due_period_during_inflight_still_records_one_skip(
        memdb, monkeypatch):
    """S4 keeps the genuine-overlap contract: when the NEXT period really arrives
    while the previous fire is still running, the tick records exactly ONE
    skipped_overlap row (and advances next_due again)."""
    spawn_id = await _seed_spawn(memdb)
    task_id = await _seed_task(memdb, spawn_id=spawn_id)
    started, release = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(scheduler.dispatcher, "dispatch",
                        _hanging_dispatch(started, release))

    await scheduler.tick()
    await asyncio.wait_for(started.wait(), 2)

    async with memdb() as db:                         # the next period arrives early
        task = await db.get(ScheduledTask, task_id)
        task.next_due_at = datetime.utcnow() - timedelta(seconds=1)
        await db.commit()

    await scheduler.tick()
    rows = await _task_runs(memdb, task_id)
    assert sorted((r.outcome or "inflight") for r in rows) == ["inflight", "skipped_overlap"]

    release.set()
    await _drain()


# ---------------------------------------------------------------------------
# single-flight at the tick level (+ review I3: one skip per due period)
# ---------------------------------------------------------------------------

async def test_tick_overlap_records_one_skip_per_due_period(memdb, monkeypatch):
    spawn_id = await _seed_spawn(memdb)
    task_id = await _seed_task(memdb, spawn_id=spawn_id)
    async with memdb() as db:
        db.add(ScheduledTaskRun(task_id=task_id, started_at=datetime.utcnow()))
        await db.commit()

    async def unreachable_dispatch(conversation_id, **kwargs):
        raise AssertionError("dispatch must not run while a run is in flight")
    monkeypatch.setattr(scheduler.dispatcher, "dispatch", unreachable_dispatch)

    await scheduler.tick()
    await _drain()
    await scheduler.tick()   # next 60s tick: the skip advanced next_due → no longer due
    await _drain()

    rows = await _task_runs(memdb, task_id)
    outcomes = [r.outcome for r in rows]
    assert outcomes.count("skipped_overlap") == 1
    assert outcomes.count(None) == 1     # the in-flight row still gates
    async with memdb() as db:
        task = await db.get(ScheduledTask, task_id)
    assert task.next_due_at > datetime.utcnow()


# ---------------------------------------------------------------------------
# kind='scheduled' survives finalize (recorder unit pin)
# ---------------------------------------------------------------------------

async def test_finalize_preserves_scheduled_kind(memdb):
    rec = await run_recorder.RunRecorder.start(
        conversation_id="scheduled-1", spawn_id=None, spawn_name="S",
        user_message="做每日早报", kind="scheduled")
    tee = rec.tee(lambda e: None)
    tee({"type": "stream_start", "source": "spawn", "spawn_id": 1, "run_id": rec.run_id})
    await rec.finalize(summary_message_id=None, full_output="ok")
    async with memdb() as db:
        run = await db.get(Run, rec.run_id)
    assert run.kind == "scheduled"       # finalize must NOT clobber it back to 'live'
    assert run.status == "recorded"
    assert run.epoch == 1


# ---------------------------------------------------------------------------
# D2 corpus isolation (structural)
# ---------------------------------------------------------------------------

async def _seed_scored_run(Session, *, spawn_id: int, kind: str, task: str,
                           output: str) -> int:
    async with Session() as db:
        run = Run(conversation_id="c", spawn_id=spawn_id, spawn_name="X",
                  user_message=task, status="scored", task_tokens=0,
                  overall_score=8.0, kind=kind, epoch=1)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        db.add(ArslanMessage(conversation_id="c", role="spawn_summary",
                             content="s", display_content=output, run_id=run.id))
        db.add(RunEvaluation(run_id=run.id, dimension="completion", status="pass",
                             score=8.0, comment="x"))
        await db.commit()
        return run.id


async def test_scheduled_runs_never_enter_replay_corpus(memdb):
    spawn_id = await _seed_spawn(memdb)
    live_id = await _seed_scored_run(memdb, spawn_id=spawn_id, kind="live",
                                     task="live-task", output="live-out")
    await _seed_scored_run(memdb, spawn_id=spawn_id, kind="scheduled",
                           task="sched-task", output="sched-out")
    items = await replay_set.build(spawn_id)
    assert [it["run_id"] for it in items] == [live_id]   # live in, scheduled out


async def test_scheduled_runs_ignored_by_evolution_watcher_count(memdb):
    spawn_id = await _seed_spawn(memdb)
    await _seed_scored_run(memdb, spawn_id=spawn_id, kind="live",
                           task="live-task", output="live-out")
    for i in range(10):
        await _seed_scored_run(memdb, spawn_id=spawn_id, kind="scheduled",
                               task=f"sched-{i}", output="o")
    async with memdb() as db:
        count = await evolution_watcher._new_replayable_run_count(db, spawn_id, None)
        assert count == 1                                # only the live run counts
        assert await evolution_watcher._is_eligible(db, spawn_id) is False


# ---------------------------------------------------------------------------
# watch_loop / start / stop
# ---------------------------------------------------------------------------

async def test_watch_loop_sweeps_orphans_ticks_and_stop_interrupts_sleep(memdb, monkeypatch):
    task_id = await _seed_task(memdb, next_due_at=None)
    async with memdb() as db:                 # orphan from a "previous process"
        db.add(ScheduledTaskRun(task_id=task_id, started_at=datetime.utcnow()))
        await db.commit()

    ticks: list[int] = []

    async def fake_tick():
        ticks.append(1)
    monkeypatch.setattr(scheduler, "tick", fake_tick)

    stop = asyncio.Event()
    loop_task = asyncio.create_task(scheduler.watch_loop(interval=60, stop_event=stop))
    # 🔴 Wait for the condition, not for a duration. A fixed 50ms sleep asserts
    # "the loop got scheduled within 50ms", which is a statement about the machine
    # rather than about the code — and a loaded CI runner failed it (assert []).
    # The bound still fails fast if the first tick genuinely never runs.
    await _wait_until(lambda: bool(ticks), "the first tick never ran")
    rows = await _task_runs(memdb, task_id)   # I2: sweep ran BEFORE the first tick
    assert rows[0].outcome == "error"
    assert rows[0].reason == "orphaned by restart"

    stop.set()
    await asyncio.wait_for(loop_task, 2)      # stop interrupts the 60s sleep


async def test_start_stop_idempotent(memdb, monkeypatch):
    async def fake_tick():
        pass
    monkeypatch.setattr(scheduler, "tick", fake_tick)

    scheduler.start(interval=60)
    first = scheduler._loop_task
    assert first is not None and not first.done()
    scheduler.start(interval=60)              # idempotent: same loop task
    assert scheduler._loop_task is first

    await scheduler.stop()
    assert scheduler._loop_task is None
    await scheduler.stop()                    # second stop is a no-op
