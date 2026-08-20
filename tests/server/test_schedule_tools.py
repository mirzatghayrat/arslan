"""Arslan schedules its own work (spec P2 §1.2).

Reuses the EXISTING service gates — the enabled quota, the interval floor, cron
validity — rather than opening a second way into the same table. A refusal
comes back readable and nothing lands in the DB.

Scheduling is spending future money, so it sits behind the same session grant
shape as a workspace write (user ruling 2026-08-20). And a agent that can
create but not list or cancel would leave the user with things they cannot find
— so all three ship together.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, ScheduledTask
from server.registry import schedule_tools


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'st.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    yield m
    await engine.dispose()


async def _count(m) -> int:
    async with m() as s:
        return len((await s.execute(select(ScheduledTask))).scalars().all())


# ── creating ──────────────────────────────────────────────────────────────
async def test_creates_an_interval_task_owned_by_arslan(db):
    out = await schedule_tools.ScheduleTaskExecutor().execute(
        {"name": "morning CI", "prompt": "summarise CI", "when": "every: 3600",
         "conversation_id": "c1"})
    assert out["ok"] is True
    async with db() as s:
        (task,) = (await s.execute(select(ScheduledTask))).scalars().all()
    assert task.spawn_id is None            # runs as Arslan itself (P2 §1.1)
    assert task.interval_s == 3600
    assert task.conversation_id == "c1"     # results land where the user is
    assert task.enabled is True


async def test_creates_a_cron_task(db):
    out = await schedule_tools.ScheduleTaskExecutor().execute(
        {"name": "daily", "prompt": "p", "when": "cron: 0 9 * * *"})
    assert out["ok"] is True
    async with db() as s:
        (task,) = (await s.execute(select(ScheduledTask))).scalars().all()
    assert task.cron == "0 9 * * *" and task.schedule_kind == "cron"


async def test_an_invalid_cron_is_refused_and_nothing_lands(db):
    out = await schedule_tools.ScheduleTaskExecutor().execute(
        {"name": "bad", "prompt": "p", "when": "cron: not a cron"})
    assert out["ok"] is False and out["error"]
    assert await _count(db) == 0


async def test_an_interval_below_the_floor_is_refused(db):
    from server.services import scheduler
    out = await schedule_tools.ScheduleTaskExecutor().execute(
        {"name": "spammy", "prompt": "p", "when": f"every: {scheduler.MIN_INTERVAL_S - 1}"})
    assert out["ok"] is False
    assert str(scheduler.MIN_INTERVAL_S) in out["error"]    # says what the floor IS
    assert await _count(db) == 0


async def test_the_enabled_quota_is_the_existing_one(db):
    """Reuses the service cap rather than inventing a second one."""
    from server.services import scheduler
    for i in range(scheduler.MAX_ENABLED):
        r = await schedule_tools.ScheduleTaskExecutor().execute(
            {"name": f"t{i}", "prompt": "p", "when": "every: 3600"})
        assert r["ok"] is True, r
    over = await schedule_tools.ScheduleTaskExecutor().execute(
        {"name": "one too many", "prompt": "p", "when": "every: 3600"})
    assert over["ok"] is False
    assert await _count(db) == scheduler.MAX_ENABLED


async def test_a_malformed_when_is_refused(db):
    for when in ("", "tomorrow", "every: soon", "cron:", "nonsense"):
        out = await schedule_tools.ScheduleTaskExecutor().execute(
            {"name": "n", "prompt": "p", "when": when})
        assert out["ok"] is False, when
    assert await _count(db) == 0


# ── listing and cancelling: what it creates, it can show and undo ─────────
async def test_lists_what_it_created(db):
    await schedule_tools.ScheduleTaskExecutor().execute(
        {"name": "one", "prompt": "p", "when": "every: 3600"})
    out = await schedule_tools.ListTasksExecutor().execute({})
    assert out["ok"] is True
    assert [t["name"] for t in out["tasks"]] == ["one"]
    assert "id" in out["tasks"][0] and "when" in out["tasks"][0]


async def test_cancels_by_id(db):
    await schedule_tools.ScheduleTaskExecutor().execute(
        {"name": "one", "prompt": "p", "when": "every: 3600"})
    listed = await schedule_tools.ListTasksExecutor().execute({})
    tid = listed["tasks"][0]["id"]
    out = await schedule_tools.CancelTaskExecutor().execute({"task_id": tid})
    assert out["ok"] is True
    assert await _count(db) == 0


async def test_cancelling_an_unknown_id_is_a_readable_refusal(db):
    out = await schedule_tools.CancelTaskExecutor().execute({"task_id": 9999})
    assert out["ok"] is False and "9999" in out["error"]


@pytest.mark.parametrize("key", ["schedule_task", "list_my_tasks", "cancel_task"])
def test_registered_in_executors(key):
    from server.registry.executors import EXECUTORS
    assert key in EXECUTORS
