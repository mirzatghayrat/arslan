"""Arslan schedules its own work (spec P2 §1.2).

Reuses the EXISTING service gates — the enabled quota, the interval floor, cron
validity — rather than opening a second way into the same table. A refusal
comes back readable and nothing lands in the DB.

Scheduling is spending future money, so it sits behind the same session grant
shape as a workspace write (user ruling 2026-08-20). And a agent that can
create but not list or cancel would leave the user with things they cannot find
— so all three ship together.

A task posts its runs into the conversation it was made in: the caller the
dispatch sets around the call, never a conversation its arguments name (C7c-3b,
review round 1). The executor runs here as the dispatch runs it (`schedule`).
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, ScheduledTask
from server.orchestrator import tool_caller
from server.registry import schedule_tools
from tests.server import scripted_turn
from tests.server.scripted_turn import (  # noqa: F401 — the fixtures
    FINDERS,
    REACHABLE,
    Reply,
    Turn,
    booted_db_fixture,
    call,
    card,
    run_turn,
    table,
    turn_db_fixture,
)

HOST = tool_caller.ToolCaller(actor="host", spawn_id=None, conversation_id="c1")


async def schedule(args: dict, caller: tool_caller.ToolCaller | None = HOST) -> dict:
    """The executor as the dispatch runs it: with the caller `tool_execute.run_executor` sets around the call, here a
    host turn in conversation `c1`."""
    token = tool_caller.set_caller(caller) if caller is not None else None
    try:
        return await schedule_tools.ScheduleTaskExecutor().execute(args)
    finally:
        if token is not None:
            tool_caller.reset_caller(token)


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
    out = await schedule({"name": "morning CI", "prompt": "summarise CI", "when": "every: 3600"})
    assert out["ok"] is True
    async with db() as s:
        (task,) = (await s.execute(select(ScheduledTask))).scalars().all()
    assert task.spawn_id is None            # runs as Arslan itself (P2 §1.1)
    assert task.interval_s == 3600
    assert task.conversation_id == "c1"     # results land in the conversation it was made in
    assert task.enabled is True


async def test_creates_a_cron_task(db):
    out = await schedule({"name": "daily", "prompt": "p", "when": "cron: 0 9 * * *"})
    assert out["ok"] is True
    async with db() as s:
        (task,) = (await s.execute(select(ScheduledTask))).scalars().all()
    assert task.cron == "0 9 * * *" and task.schedule_kind == "cron"


async def test_a_task_scheduled_through_use_tool_binds_to_the_conversation_it_was_made_in(monkeypatch, turn_db):
    """use_tool's `arguments` may carry a field the tool's table doesn't list (`_schema_problem` reads only the listed
    ones), and the card shows no conversation. One naming another conversation reaches the executor through the real
    unwrap, card and dispatch; the task still posts into the conversation the call ran in."""
    turn = Turn()
    monkeypatch.delitem(scripted_turn.ANSWERS, "schedule_task")         # the real executor, and the row it writes
    asked = {"name": "n", "when": "every: 3600", "prompt": "p", "conversation_id": "c-other"}

    async def reachable():
        return [*REACHABLE, *table("schedule_task")]
    await run_turn(turn, monkeypatch, turn_db, [call("use_tool", {"name": "schedule_task", "arguments": asked}),
                                                Reply("Scheduled.")],
                   tools=FINDERS, resolve_callable=reachable, confirm_schedule=card(turn, "schedule"),
                   conversation_id="c1", caller=HOST)
    [step] = turn.returned["tool_trace"]
    assert (step["tool"], step["args"], step["result"]["ok"]) == ("schedule_task", asked, True)   # unwrapped, ran
    assert turn.cards == [("schedule", ["n", "every: 3600"], {"prompt": "p"})]
    async with turn_db() as s:
        (task,) = (await s.execute(select(ScheduledTask))).scalars().all()
    assert task.conversation_id == "c1"


@pytest.mark.parametrize("caller", [None, tool_caller.ToolCaller(actor="host", spawn_id=None, conversation_id=None)],
                         ids=["no caller", "a caller with no conversation"])
async def test_with_no_conversation_to_bind_to_nothing_is_scheduled(db, caller):
    """Every path that offers the tool runs it with a caller and its conversation. Without one there is nothing to bind
    the task to, and a row stored with none would post into `scheduled-<id>`, which is a deleted task's conversation
    once SQLite reuses that id (scheduler.own_conversation): refused, and nothing lands."""
    out = await schedule({"name": "n", "prompt": "p", "when": "every: 3600", "conversation_id": "c-other"}, caller)
    assert out["ok"] is False and "no conversation" in out["error"]
    assert await _count(db) == 0


async def test_an_invalid_cron_is_refused_and_nothing_lands(db):
    out = await schedule({"name": "bad", "prompt": "p", "when": "cron: not a cron"})
    assert out["ok"] is False and out["error"]
    assert await _count(db) == 0


async def test_an_interval_below_the_floor_is_refused(db):
    from server.services import scheduler
    out = await schedule({"name": "spammy", "prompt": "p", "when": f"every: {scheduler.MIN_INTERVAL_S - 1}"})
    assert out["ok"] is False
    assert str(scheduler.MIN_INTERVAL_S) in out["error"]    # says what the floor IS
    assert await _count(db) == 0


async def test_the_enabled_quota_is_the_existing_one(db):
    """Reuses the service cap rather than inventing a second one."""
    from server.services import scheduler
    for i in range(scheduler.MAX_ENABLED):
        r = await schedule({"name": f"t{i}", "prompt": "p", "when": "every: 3600"})
        assert r["ok"] is True, r
    over = await schedule({"name": "one too many", "prompt": "p", "when": "every: 3600"})
    assert over["ok"] is False
    assert await _count(db) == scheduler.MAX_ENABLED


async def test_a_malformed_when_is_refused(db):
    for when in ("", "tomorrow", "every: soon", "cron:", "nonsense"):
        out = await schedule({"name": "n", "prompt": "p", "when": when})
        assert out["ok"] is False, when
    assert await _count(db) == 0


# ── listing and cancelling: what it creates, it can show and undo ─────────
async def test_lists_what_it_created(db):
    await schedule({"name": "one", "prompt": "p", "when": "every: 3600"})
    out = await schedule_tools.ListTasksExecutor().execute({})
    assert out["ok"] is True
    assert [t["name"] for t in out["tasks"]] == ["one"]
    assert "id" in out["tasks"][0] and "when" in out["tasks"][0]


async def test_cancels_by_id(db):
    await schedule({"name": "one", "prompt": "p", "when": "every: 3600"})
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
