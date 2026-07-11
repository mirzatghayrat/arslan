"""S3-M4 Task 1: scheduled_tasks tables + scheduler pure core.

Contract under test:
  - migration _0030 creates scheduled_tasks + scheduled_task_runs idempotently
    (repo re-applies every migration on every boot);
  - parse_cron accepts exactly the YAGNI grammar (5 fields; *, number, */n, comma
    lists) and rejects everything else with ValueError;
  - cron_next returns the next matching minute STRICTLY after `after`;
  - compute_next_due: disabled -> None; interval/cron always computed FORWARD from
    now — MISSED FIRES ARE NOT REPLAYED (no catch-up);
  - due_tasks filters enabled + next_due_at <= now;
  - single-flight: has_inflight + record_skip_overlap;
  - record_outcome: ok resets failures + advances last_fired/next_due; 3 consecutive
    failures auto-pause the task and post a conversation notification + best-effort
    recap event — notification failure NEVER breaks the outcome write.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import ArslanMessage, Base, ScheduledTask, ScheduledTaskRun
from server.services import recap_service, scheduler
from server.orchestrator import memory


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session
    await engine.dispose()


async def _seed_task(Session, **overrides) -> int:
    fields = dict(name="早报", prompt="做每日早报", schedule_kind="interval",
                  interval_s=3600, enabled=True, consecutive_failures=0)
    fields.update(overrides)
    async with Session() as db:
        task = ScheduledTask(**fields)
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task.id


async def _add_inflight(Session, task_id: int) -> int:
    async with Session() as db:
        row = ScheduledTaskRun(task_id=task_id, started_at=datetime.utcnow())
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _get(Session, model, pk):
    async with Session() as db:
        return await db.get(model, pk)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

async def test_0030_creates_tables_idempotent():
    from server.db.migrations.versions._0030_scheduled_tasks import upgrade_sync
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            # PRE-EXISTING-DB path: run the migration WITHOUT create_all first.
            await conn.run_sync(upgrade_sync)
            await conn.run_sync(upgrade_sync)  # idempotent
            tables = {r[0] for r in (await conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"))}
            assert {"scheduled_tasks", "scheduled_task_runs"} <= tables
            task_cols = {r[1] for r in (await conn.exec_driver_sql(
                "PRAGMA table_info(scheduled_tasks)"))}
            assert {"id", "name", "prompt", "spawn_id", "conversation_id",
                    "schedule_kind", "interval_s", "cron", "enabled", "last_fired_at",
                    "next_due_at", "consecutive_failures", "paused_reason",
                    "created_at"} <= task_cols
            run_cols = {r[1] for r in (await conn.exec_driver_sql(
                "PRAGMA table_info(scheduled_task_runs)"))}
            assert {"id", "task_id", "started_at", "finished_at", "outcome",
                    "run_id", "reason"} <= run_cols
            # boot order parity: create_all AFTER the migration must also be a no-op
            await conn.run_sync(Base.metadata.create_all)
            idx = {r[0] for r in (await conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='index'"))}
            assert "ix_scheduled_tasks_next_due_at" in idx
            assert "ix_scheduled_task_runs_task_id" in idx
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Guardrail constants (approved decision D1)
# ---------------------------------------------------------------------------

def test_guardrail_constants():
    assert scheduler.MIN_INTERVAL_S == 900
    assert scheduler.MAX_ENABLED == 10


# ---------------------------------------------------------------------------
# parse_cron
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expr", [
    "* * * * *",
    "0 9 * * *",
    "*/15 * * * *",
    "0,30 9,18 1,15 6,12 0,6",
    "59 23 31 12 6",
])
def test_parse_cron_accepts(expr):
    scheduler.parse_cron(expr)  # must not raise


@pytest.mark.parametrize("expr", [
    "",                  # empty
    "* * * *",           # 4 fields
    "* * * * * *",       # 6 fields
    "60 * * * *",        # minute out of range
    "* 24 * * *",        # hour out of range
    "* * 0 * *",         # day-of-month below range
    "* * 32 * *",        # day-of-month above range
    "* * * 0 *",         # month below range
    "* * * 13 *",        # month above range
    "* * * * 7",         # day-of-week out of range (0-6)
    "*/0 * * * *",       # zero step
    "*/x * * * *",       # garbage step
    "abc * * * *",       # garbage value
    "1-5 * * * *",       # ranges unsupported (YAGNI)
    "1,x * * * *",       # garbage inside comma list
    "-1 * * * *",        # negative
])
def test_parse_cron_rejects(expr):
    with pytest.raises(ValueError):
        scheduler.parse_cron(expr)


# ---------------------------------------------------------------------------
# cron_next
# ---------------------------------------------------------------------------

def test_cron_next_daily_after_todays_slot():
    got = scheduler.cron_next("0 9 * * *", datetime(2026, 7, 12, 10, 0))
    assert got == datetime(2026, 7, 13, 9, 0)


def test_cron_next_daily_before_todays_slot():
    got = scheduler.cron_next("0 9 * * *", datetime(2026, 7, 12, 8, 30))
    assert got == datetime(2026, 7, 12, 9, 0)


def test_cron_next_every_15_minutes():
    got = scheduler.cron_next("*/15 * * * *", datetime(2026, 7, 12, 10, 7))
    assert got == datetime(2026, 7, 12, 10, 15)


def test_cron_next_is_strictly_after():
    got = scheduler.cron_next("*/15 * * * *", datetime(2026, 7, 12, 10, 15))
    assert got == datetime(2026, 7, 12, 10, 30)


def test_cron_next_weekday():
    # 2026-07-12 is a Sunday; cron dow 1 = Monday -> next day 09:00.
    got = scheduler.cron_next("0 9 * * 1", datetime(2026, 7, 12, 10, 0))
    assert got == datetime(2026, 7, 13, 9, 0)
    # cron dow 0 = Sunday; today's 09:00 already passed -> next Sunday.
    got = scheduler.cron_next("0 9 * * 0", datetime(2026, 7, 12, 10, 0))
    assert got == datetime(2026, 7, 19, 9, 0)


def test_cron_next_comma_list():
    got = scheduler.cron_next("0,30 9 * * *", datetime(2026, 7, 12, 9, 10))
    assert got == datetime(2026, 7, 12, 9, 30)


def test_cron_next_impossible_date_raises():
    with pytest.raises(ValueError):
        scheduler.cron_next("0 0 31 2 *", datetime(2026, 7, 12, 10, 0))


# ---------------------------------------------------------------------------
# compute_next_due — MISSED FIRES ARE NOT REPLAYED
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 12, 10, 0)


def test_compute_next_due_disabled_is_none():
    task = ScheduledTask(name="t", prompt="p", schedule_kind="interval",
                         interval_s=3600, enabled=False)
    assert scheduler.compute_next_due(task, _NOW) is None


def test_compute_next_due_interval_never_fired():
    task = ScheduledTask(name="t", prompt="p", schedule_kind="interval",
                         interval_s=3600, enabled=True, last_fired_at=None)
    assert scheduler.compute_next_due(task, _NOW) == _NOW + timedelta(hours=1)


def test_compute_next_due_interval_normal():
    task = ScheduledTask(name="t", prompt="p", schedule_kind="interval",
                         interval_s=3600, enabled=True,
                         last_fired_at=_NOW - timedelta(minutes=10))
    assert scheduler.compute_next_due(task, _NOW) == _NOW + timedelta(minutes=50)


def test_compute_next_due_interval_no_catch_up():
    """last_fired 3 days ago with a 1h interval -> due NOW, not now-3d+1h and not
    72 replayed fires: next_due is always computed forward from now."""
    task = ScheduledTask(name="t", prompt="p", schedule_kind="interval",
                         interval_s=3600, enabled=True,
                         last_fired_at=_NOW - timedelta(days=3))
    assert scheduler.compute_next_due(task, _NOW) == _NOW


def test_compute_next_due_cron():
    task = ScheduledTask(name="t", prompt="p", schedule_kind="cron",
                         cron="0 9 * * *", enabled=True, last_fired_at=None)
    assert scheduler.compute_next_due(task, _NOW) == datetime(2026, 7, 13, 9, 0)


def test_compute_next_due_cron_no_catch_up():
    """Cron task last fired days ago: next_due is the next slot after NOW —
    the missed slots in between are never replayed."""
    task = ScheduledTask(name="t", prompt="p", schedule_kind="cron",
                         cron="0 9 * * *", enabled=True,
                         last_fired_at=_NOW - timedelta(days=3))
    assert scheduler.compute_next_due(task, _NOW) == datetime(2026, 7, 13, 9, 0)


# ---------------------------------------------------------------------------
# due_tasks
# ---------------------------------------------------------------------------

async def test_due_tasks_filters(memdb):
    now = datetime.utcnow()
    due_id = await _seed_task(memdb, name="due", next_due_at=now - timedelta(minutes=1))
    await _seed_task(memdb, name="future", next_due_at=now + timedelta(hours=1))
    await _seed_task(memdb, name="disabled", enabled=False,
                     next_due_at=now - timedelta(minutes=1))
    await _seed_task(memdb, name="no-due", next_due_at=None)
    got = await scheduler.due_tasks(now)
    assert [t.id for t in got] == [due_id]


# ---------------------------------------------------------------------------
# single-flight: has_inflight + record_skip_overlap
# ---------------------------------------------------------------------------

async def test_has_inflight_and_skip_overlap(memdb):
    task_id = await _seed_task(memdb)
    assert await scheduler.has_inflight(task_id) is False

    await _add_inflight(memdb, task_id)
    assert await scheduler.has_inflight(task_id) is True

    await scheduler.record_skip_overlap(task_id)
    async with memdb() as db:
        rows = list((await db.execute(
            select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == task_id)
            .order_by(ScheduledTaskRun.id))).scalars().all())
    assert len(rows) == 2
    skip = rows[1]
    assert skip.outcome == "skipped_overlap"
    assert skip.started_at is not None and skip.finished_at is not None
    # the skip row is finalized, so the ONE in-flight row still gates
    assert await scheduler.has_inflight(task_id) is True


# ---------------------------------------------------------------------------
# record_outcome
# ---------------------------------------------------------------------------

async def test_record_outcome_ok_resets_and_advances(memdb):
    task_id = await _seed_task(memdb, consecutive_failures=2)
    run_row_id = await _add_inflight(memdb, task_id)

    await scheduler.record_outcome(task_id, True, run_id=42)

    row = await _get(memdb, ScheduledTaskRun, run_row_id)
    assert row.outcome == "ok"
    assert row.finished_at is not None
    assert row.run_id == 42
    task = await _get(memdb, ScheduledTask, task_id)
    assert task.consecutive_failures == 0
    assert task.last_fired_at is not None
    assert task.next_due_at == task.last_fired_at + timedelta(seconds=3600)
    assert await scheduler.has_inflight(task_id) is False


async def test_record_outcome_reason_truncated_to_2000(memdb):
    task_id = await _seed_task(memdb)
    run_row_id = await _add_inflight(memdb, task_id)
    await scheduler.record_outcome(task_id, False, reason="x" * 3000)
    row = await _get(memdb, ScheduledTaskRun, run_row_id)
    assert row.outcome == "error"
    assert len(row.reason) == 2000


async def test_record_outcome_three_failures_pause_and_notify(memdb, monkeypatch):
    events: list[tuple] = []

    async def fake_log_event(conversation_id, kind, ref, summary):
        events.append((conversation_id, kind, ref, summary))
    monkeypatch.setattr(recap_service, "log_event", fake_log_event)

    task_id = await _seed_task(memdb, name="早报", conversation_id="c-sched")

    for i in range(1, 3):
        await _add_inflight(memdb, task_id)
        await scheduler.record_outcome(task_id, False, reason="boom")
        task = await _get(memdb, ScheduledTask, task_id)
        assert task.consecutive_failures == i
        assert task.enabled is True
        assert task.paused_reason is None

    await _add_inflight(memdb, task_id)
    await scheduler.record_outcome(task_id, False, reason="boom")

    task = await _get(memdb, ScheduledTask, task_id)
    assert task.enabled is False
    assert task.consecutive_failures == 3
    assert "boom" in (task.paused_reason or "")
    assert task.next_due_at is None

    # notification message posted into the task's conversation
    async with memdb() as db:
        msgs = list((await db.execute(
            select(ArslanMessage).where(
                ArslanMessage.conversation_id == "c-sched"))).scalars().all())
    assert len(msgs) == 1
    assert msgs[0].role == "arslan"
    assert "定时任务「早报」" in msgs[0].content
    assert "boom" in msgs[0].content

    # best-effort recap event
    assert len(events) == 1
    assert events[0][0] == "c-sched"
    assert events[0][1] == "scheduled_pause"


async def test_pause_notification_failure_never_breaks_outcome_write(memdb, monkeypatch):
    async def broken_add_message(*a, **kw):
        raise RuntimeError("socket down")

    async def broken_log_event(*a, **kw):
        raise RuntimeError("events table locked")
    monkeypatch.setattr(memory, "add_message", broken_add_message)
    monkeypatch.setattr(recap_service, "log_event", broken_log_event)

    task_id = await _seed_task(memdb, conversation_id="c-x", consecutive_failures=2)
    run_row_id = await _add_inflight(memdb, task_id)

    await scheduler.record_outcome(task_id, False, reason="boom")  # must not raise

    row = await _get(memdb, ScheduledTaskRun, run_row_id)
    assert row.outcome == "error"
    task = await _get(memdb, ScheduledTask, task_id)
    assert task.enabled is False
    assert task.consecutive_failures == 3
