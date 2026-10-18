"""A scheduled task with no spawn runs ARSLAN itself (spec P2 §1.1).

§5 named this the round's number-one risk: handle_user_message has only ever
run with a live socket behind its emit and its two confirm callbacks, and
nothing proved it works without one. That is what the first test here is for —
proving it, not assuming it.

The safety property is STRUCTURAL rather than a new policy: a timed fire has no
socket, so it passes no confirm callbacks, so P1's "no callback means refuse"
makes writes and commands impossible in an unattended run. That is precisely
the unattended-exec surface the two arXiv analyses of OpenClaw are about, and
here it closes by construction.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, ScheduledTask, ScheduledTaskRun


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'sched.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    yield m
    await engine.dispose()


# ── the risk, proven first ────────────────────────────────────────────────
async def test_arslan_turn_runs_with_no_socket_behind_it(db, monkeypatch):
    """The headline risk from the spec: no WS, no emit sink, no callbacks."""
    from server.orchestrator import arslan as arslan_mod

    seen = {}

    async def fake_answer(conversation_id, user_message, emit, **kw):
        seen["cid"] = conversation_id
        seen["msg"] = user_message
        seen["confirm_command"] = kw.get("confirm_command")
        seen["confirm_workspace_write"] = kw.get("confirm_workspace_write")
        emit({"type": "stream_start", "source": "arslan"})
        emit({"type": "stream_end", "message_id": 1})
        return "done"

    monkeypatch.setattr(arslan_mod, "_handle_answer", fake_answer)

    from server.services import scheduler
    await scheduler.run_arslan_turn("sched-conv", "summarise CI")

    assert seen["msg"] == "summarise CI"
    # The whole safety argument in two assertions:
    assert seen["confirm_command"] is None
    assert seen["confirm_workspace_write"] is None


async def test_frames_go_to_the_registry_fanout_not_a_dead_socket(db, monkeypatch):
    """With a tab open the user sees it live; with none, the frames simply
    drop — never an exception for want of a listener."""
    from server.orchestrator import arslan as arslan_mod
    from server.services import run_registry, scheduler

    got = []
    run_registry.attach_sink("sched-conv", got.append)
    try:
        async def fake_answer(conversation_id, user_message, emit, **kw):
            emit({"type": "stream_chunk", "content": "hello"})
            return "done"
        monkeypatch.setattr(arslan_mod, "_handle_answer", fake_answer)
        await scheduler.run_arslan_turn("sched-conv", "hi")
    finally:
        run_registry.detach_sink("sched-conv", got.append)
    assert {"type": "stream_chunk", "content": "hello"} in got


async def test_no_listener_is_not_an_error(db, monkeypatch):
    from server.orchestrator import arslan as arslan_mod
    from server.services import scheduler

    async def fake_answer(conversation_id, user_message, emit, **kw):
        emit({"type": "stream_chunk", "content": "nobody is watching"})
        return "done"
    monkeypatch.setattr(arslan_mod, "_handle_answer", fake_answer)
    await scheduler.run_arslan_turn("nobody-here", "hi")   # must not raise


# ── every fire is an Arslan turn ──────────────────────────────────────────
async def _task(m, **kw):
    from datetime import datetime
    async with m() as s:
        t = ScheduledTask(name=kw.get("name", "t"), prompt=kw.get("prompt", "p"),
                          spawn_id=kw.get("spawn_id"), conversation_id=kw.get("cid"),
                          target=("spawn" if kw.get("spawn_id") else "arslan"),
                          schedule_kind="interval", interval_s=900, enabled=True,
                          next_due_at=datetime.utcnow())
        s.add(t)
        await s.commit()
        return t.id


async def test_a_task_without_a_spawn_fires_an_arslan_turn(db, monkeypatch):
    from server.services import scheduler

    called = []

    async def fake_turn(cid, prompt):
        called.append((cid, prompt))
    monkeypatch.setattr(scheduler, "run_arslan_turn", fake_turn)

    tid = await _task(db, prompt="check the news", cid="conv-x")
    async with db() as s:
        task = await s.get(ScheduledTask, tid)
    await scheduler._fire(task)

    assert called == [("conv-x", "check the news")]


@pytest.mark.parametrize("spawn_id", [42, None], ids=["spawn-kept", "spawn-deleted"])
async def test_an_old_expert_row_fires_as_an_arslan_turn(db, monkeypatch, spawn_id):
    """0.1.63 (C1): a row an older build wrote with target="spawn" (migration 0056
    rewrites stored rows; this is one it missed) runs as an Arslan turn, whether
    its spawn still exists or was deleted (spawn_id SET NULL). No expert is
    dispatched, and the fire is an ordinary ok outcome."""
    from sqlalchemy import select

    from server.orchestrator import dispatcher
    from server.services import scheduler

    arslan_turns, dispatches = [], []

    async def fake_turn(cid, prompt):
        arslan_turns.append((cid, prompt))
    monkeypatch.setattr(scheduler, "run_arslan_turn", fake_turn)

    async def fake_dispatch(*args, **kwargs):
        dispatches.append(args)
        raise AssertionError("an expert was dispatched")
    monkeypatch.setattr(dispatcher, "dispatch", fake_dispatch)

    tid = await _task(db, prompt="do it", cid="conv-y")
    async with db() as s:
        task = await s.get(ScheduledTask, tid)
        task.target, task.spawn_id = "spawn", spawn_id
        await s.commit()
        task = await s.get(ScheduledTask, tid)
    await scheduler._fire(task)

    assert arslan_turns == [("conv-y", "do it")]
    assert dispatches == []
    async with db() as s:
        rows = (await s.execute(
            select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == tid))).scalars().all()
    assert [r.outcome for r in rows] == ["ok"]


async def test_the_arslan_fire_records_an_outcome(db, monkeypatch):
    """Every exit records against its in-flight row — the property the whole
    auto-pause counter rests on."""
    from sqlalchemy import select

    from server.services import scheduler

    async def fake_turn(cid, prompt):
        return None
    monkeypatch.setattr(scheduler, "run_arslan_turn", fake_turn)

    tid = await _task(db, cid="conv-z")
    async with db() as s:
        task = await s.get(ScheduledTask, tid)
    await scheduler._fire(task)

    async with db() as s:
        rows = (await s.execute(
            select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == tid))).scalars().all()
    assert len(rows) == 1 and rows[0].outcome == "ok"


async def test_a_failing_arslan_turn_is_an_error_outcome_not_a_crash(db, monkeypatch):
    from sqlalchemy import select

    from server.services import scheduler

    async def boom(cid, prompt):
        raise RuntimeError("model down")
    monkeypatch.setattr(scheduler, "run_arslan_turn", boom)

    tid = await _task(db, cid="conv-e")
    async with db() as s:
        task = await s.get(ScheduledTask, tid)
    await scheduler._fire(task)               # must not raise

    async with db() as s:
        rows = (await s.execute(
            select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == tid))).scalars().all()
    assert rows[0].outcome == "error"


async def test_migration_backfills_existing_tasks_to_spawn(tmp_path):
    """Every task that predates the column was created through an API that
    REQUIRED a spawn — 'spawn' is their history, not a guess."""
    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine

    from server.db.migrations.versions._0041_scheduled_task_target import upgrade_sync

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'m41.db'}")
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "CREATE TABLE scheduled_tasks (id INTEGER PRIMARY KEY, name VARCHAR(80) NOT NULL, "
            "prompt TEXT NOT NULL, schedule_kind VARCHAR(10) NOT NULL)")
        await conn.exec_driver_sql(
            "INSERT INTO scheduled_tasks (id, name, prompt, schedule_kind) "
            "VALUES (1, 'legacy', 'p', 'interval')")
        await conn.run_sync(upgrade_sync)
        await conn.run_sync(upgrade_sync)          # idempotent
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda c: {x["name"] for x in inspect(c).get_columns("scheduled_tasks")})
        val = (await conn.exec_driver_sql("SELECT target FROM scheduled_tasks WHERE id=1")).scalar()
    assert "target" in cols and val == "spawn"
    await engine.dispose()
