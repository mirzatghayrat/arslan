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

Task 1 review hardening (folded into Task 2):
  - I1: a cron with no future match must PAUSE the task on the ok-path recompute,
    never wedge the outcome write;
  - I2: sweep_orphans finalizes in-flight rows left by a dead process;
  - I3: record_skip_overlap advances next_due_at — one skip row per due period;
  - I4: vixie either-match pins (dom+dow both restricted → OR; single → AND);
  - I5: cron is interpreted in the USER'S LOCAL wall clock (matching happens in
    local time; storage stays utc-naive) — tests pin the _to_local/_to_utc seams;
  - S6: record_outcome targets the EXPLICIT in-flight row id (no latest-NULL race).
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
def utc_is_local(monkeypatch):
    """Pin the I5 local-time seams to identity so cron matching tests read as pure
    wall-clock logic, independent of the machine's timezone."""
    monkeypatch.setattr(scheduler, "_to_local", lambda dt: dt)
    monkeypatch.setattr(scheduler, "_to_utc", lambda dt: dt)


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

def test_cron_next_daily_after_todays_slot(utc_is_local):
    got = scheduler.cron_next("0 9 * * *", datetime(2026, 7, 12, 10, 0))
    assert got == datetime(2026, 7, 13, 9, 0)


def test_cron_next_daily_before_todays_slot(utc_is_local):
    got = scheduler.cron_next("0 9 * * *", datetime(2026, 7, 12, 8, 30))
    assert got == datetime(2026, 7, 12, 9, 0)


def test_cron_next_every_15_minutes(utc_is_local):
    got = scheduler.cron_next("*/15 * * * *", datetime(2026, 7, 12, 10, 7))
    assert got == datetime(2026, 7, 12, 10, 15)


def test_cron_next_is_strictly_after(utc_is_local):
    got = scheduler.cron_next("*/15 * * * *", datetime(2026, 7, 12, 10, 15))
    assert got == datetime(2026, 7, 12, 10, 30)


def test_cron_next_weekday(utc_is_local):
    # 2026-07-12 is a Sunday; cron dow 1 = Monday -> next day 09:00.
    got = scheduler.cron_next("0 9 * * 1", datetime(2026, 7, 12, 10, 0))
    assert got == datetime(2026, 7, 13, 9, 0)
    # cron dow 0 = Sunday; today's 09:00 already passed -> next Sunday.
    got = scheduler.cron_next("0 9 * * 0", datetime(2026, 7, 12, 10, 0))
    assert got == datetime(2026, 7, 19, 9, 0)


def test_cron_next_comma_list(utc_is_local):
    got = scheduler.cron_next("0,30 9 * * *", datetime(2026, 7, 12, 9, 10))
    assert got == datetime(2026, 7, 12, 9, 30)


def test_cron_next_impossible_date_raises(utc_is_local):
    with pytest.raises(ValueError):
        scheduler.cron_next("0 0 31 2 *", datetime(2026, 7, 12, 10, 0))


# I4: vixie either-match rule pins (implementation was already correct — keep it so)

def test_cron_vixie_dom_and_dow_both_restricted_is_or(utc_is_local):
    # dom=13 AND dow=5 (Friday) both restricted → a day matches if EITHER does.
    # From Sunday 2026-07-12, Monday July 13 matches dom even though it is not Friday.
    got = scheduler.cron_next("0 9 13 * 5", datetime(2026, 7, 12, 10, 0))
    assert got == datetime(2026, 7, 13, 9, 0)


def test_cron_single_day_restriction_is_and(utc_is_local):
    # Only dow restricted (dom wildcard) → plain AND: next Friday, not the next 13th.
    got = scheduler.cron_next("0 9 * * 5", datetime(2026, 7, 12, 10, 0))
    assert got == datetime(2026, 7, 17, 9, 0)


# I5: cron is interpreted in the user's LOCAL wall clock; storage stays utc-naive

def test_cron_next_matches_in_local_time(monkeypatch):
    # Freeze local = utc + 5h via the conversion seams.
    monkeypatch.setattr(scheduler, "_to_local", lambda dt: dt + timedelta(hours=5))
    monkeypatch.setattr(scheduler, "_to_utc", lambda dt: dt - timedelta(hours=5))
    # utc 05:30 = local 10:30 → today's local 09:00 passed → tomorrow 09:00 local = 04:00 utc
    got = scheduler.cron_next("0 9 * * *", datetime(2026, 7, 12, 5, 30))
    assert got == datetime(2026, 7, 13, 4, 0)
    # utc 03:00 = local 08:00 → today's local 09:00 = utc 04:00 today
    got = scheduler.cron_next("0 9 * * *", datetime(2026, 7, 12, 3, 0))
    assert got == datetime(2026, 7, 12, 4, 0)


def test_cron_next_real_seams_roundtrip_to_local_slot():
    """No monkeypatch: whatever this machine's timezone is, the returned utc-naive
    instant must read 09:30 on the LOCAL wall clock."""
    got = scheduler.cron_next("30 9 * * *", datetime(2026, 7, 12, 10, 0))
    local = scheduler._to_local(got)
    assert (local.hour, local.minute) == (9, 30)
    assert scheduler._to_utc(local) == got


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


def test_compute_next_due_cron(utc_is_local):
    task = ScheduledTask(name="t", prompt="p", schedule_kind="cron",
                         cron="0 9 * * *", enabled=True, last_fired_at=None)
    assert scheduler.compute_next_due(task, _NOW) == datetime(2026, 7, 13, 9, 0)


def test_compute_next_due_cron_no_catch_up(utc_is_local):
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


async def test_record_skip_overlap_advances_next_due(memdb):
    """Review I3: a skip consumes the due period — next_due_at moves STRICTLY past
    now, so a 60s tick loop records ONE skip row per period, not one per tick."""
    now = datetime.utcnow()
    task_id = await _seed_task(memdb, next_due_at=now - timedelta(minutes=5))
    await _add_inflight(memdb, task_id)

    await scheduler.record_skip_overlap(task_id)

    task = await _get(memdb, ScheduledTask, task_id)
    assert task.next_due_at > datetime.utcnow()
    # interval anchors at the skip time, not at the stale last_fired_at
    assert task.next_due_at <= datetime.utcnow() + timedelta(seconds=3600)


# ---------------------------------------------------------------------------
# I2: startup sweep — orphaned in-flight rows never wedge a task
# ---------------------------------------------------------------------------

async def test_sweep_orphans_finalizes_and_unblocks(memdb):
    task_id = await _seed_task(memdb)
    row_id = await _add_inflight(memdb, task_id)

    swept = await scheduler.sweep_orphans()
    assert swept == 1

    row = await _get(memdb, ScheduledTaskRun, row_id)
    assert row.outcome == "error"
    assert row.reason == "orphaned by restart"
    assert row.finished_at is not None
    assert await scheduler.has_inflight(task_id) is False   # task fireable again

    assert await scheduler.sweep_orphans() == 0             # idempotent


# ---------------------------------------------------------------------------
# record_outcome
# ---------------------------------------------------------------------------

async def test_record_outcome_ok_resets_and_advances(memdb):
    task_id = await _seed_task(memdb, consecutive_failures=2)
    run_row_id = await _add_inflight(memdb, task_id)

    await scheduler.record_outcome(task_id, True, row_id=run_row_id, run_id=42)

    row = await _get(memdb, ScheduledTaskRun, run_row_id)
    assert row.outcome == "ok"
    assert row.finished_at is not None
    assert row.run_id == 42
    task = await _get(memdb, ScheduledTask, task_id)
    assert task.consecutive_failures == 0
    assert task.last_fired_at is not None
    assert task.next_due_at == task.last_fired_at + timedelta(seconds=3600)
    assert await scheduler.has_inflight(task_id) is False


async def test_record_outcome_targets_explicit_row(memdb):
    """Review S6: the outcome lands on the EXPLICIT row id passed by the caller —
    a concurrently opened newer in-flight row (fire-now racing a tick) must never
    be cross-attached."""
    task_id = await _seed_task(memdb)
    first = await _add_inflight(memdb, task_id)
    second = await _add_inflight(memdb, task_id)

    await scheduler.record_outcome(task_id, True, row_id=first, run_id=1)

    assert (await _get(memdb, ScheduledTaskRun, first)).outcome == "ok"
    assert (await _get(memdb, ScheduledTaskRun, second)).outcome is None


async def test_record_outcome_reason_truncated_to_2000(memdb):
    task_id = await _seed_task(memdb)
    run_row_id = await _add_inflight(memdb, task_id)
    await scheduler.record_outcome(task_id, False, row_id=run_row_id, reason="x" * 3000)
    row = await _get(memdb, ScheduledTaskRun, run_row_id)
    assert row.outcome == "error"
    assert len(row.reason) == 2000


async def test_record_outcome_ok_cron_without_future_match_pauses(memdb):
    """Review I1: the ok-path recompute must never wedge the outcome write. A cron
    like `0 0 31 2 *` (Feb 31 never exists) raises in cron_next — the task is
    auto-paused instead, and the run row still finalizes ok."""
    task_id = await _seed_task(memdb, schedule_kind="cron", interval_s=None,
                               cron="0 0 31 2 *")
    run_row_id = await _add_inflight(memdb, task_id)

    await scheduler.record_outcome(task_id, True, row_id=run_row_id, run_id=7)  # no raise

    row = await _get(memdb, ScheduledTaskRun, run_row_id)
    assert row.outcome == "ok"                      # the outcome write landed
    assert row.run_id == 7
    task = await _get(memdb, ScheduledTask, task_id)
    assert task.enabled is False                    # paused, not wedged
    assert "cron 无未来匹配" in (task.paused_reason or "")
    assert task.next_due_at is None
    assert task.last_fired_at is not None


async def test_record_outcome_three_failures_pause_and_notify(memdb, monkeypatch):
    events: list[tuple] = []

    async def fake_log_event(conversation_id, kind, ref, summary):
        events.append((conversation_id, kind, ref, summary))
    monkeypatch.setattr(recap_service, "log_event", fake_log_event)

    task_id = await _seed_task(memdb, name="早报", conversation_id="c-sched")

    for i in range(1, 3):
        row_id = await _add_inflight(memdb, task_id)
        await scheduler.record_outcome(task_id, False, row_id=row_id, reason="boom")
        task = await _get(memdb, ScheduledTask, task_id)
        assert task.consecutive_failures == i
        assert task.enabled is True
        assert task.paused_reason is None

    row_id = await _add_inflight(memdb, task_id)
    await scheduler.record_outcome(task_id, False, row_id=row_id, reason="boom")

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

    await scheduler.record_outcome(task_id, False, row_id=run_row_id,
                                   reason="boom")  # must not raise

    row = await _get(memdb, ScheduledTaskRun, run_row_id)
    assert row.outcome == "error"
    task = await _get(memdb, ScheduledTask, task_id)
    assert task.enabled is False
    assert task.consecutive_failures == 3
