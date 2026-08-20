"""The heartbeat checklist (spec P2 §1.3; user rulings 2026-08-20 ②③).

A list the user writes, read on a cadence by an Arslan turn that decides
whether anything on it needs doing right now. Stored in Settings rather than
in the workspace — putting it in a file would make this feature require the
workspace feature, coupling two things that have no reason to be coupled (裁决②).

DEFAULT OFF, and the round's whole posture rides on the turn it uses: a
heartbeat run reaches the user as a MESSAGE, never as an action, because it
goes through the unattended path where writes and commands are structurally
refused. It proposes; you decide.
"""
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, ScheduledTask, Setting
from server.services import heartbeat


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'hb.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    yield m
    await engine.dispose()


async def _set(m, **kv):
    async with m() as s:
        for k, v in kv.items():
            s.add(Setting(key=k, value=v))
        await s.commit()


# ── default off ───────────────────────────────────────────────────────────
async def test_default_off_means_no_task_and_no_run(db):
    await heartbeat.sync_task()
    async with db() as s:
        assert (await s.execute(select(ScheduledTask))).scalars().all() == []


async def test_enabling_without_a_checklist_still_creates_nothing(db):
    """An empty list has nothing to check; a task firing on it would spend
    tokens to conclude 'nothing to do' forever."""
    await _set(db, heartbeat_enabled="true", heartbeat_checklist="   ")
    await heartbeat.sync_task()
    async with db() as s:
        assert (await s.execute(select(ScheduledTask))).scalars().all() == []


# ── enabling ──────────────────────────────────────────────────────────────
async def test_enabling_with_a_checklist_creates_one_arslan_task(db):
    await _set(db, heartbeat_enabled="true", heartbeat_checklist="- watch CI\n- chase invoices")
    await heartbeat.sync_task()
    async with db() as s:
        tasks = (await s.execute(select(ScheduledTask))).scalars().all()
    assert len(tasks) == 1
    t = tasks[0]
    assert t.target == "arslan"                     # runs through the unattended path
    assert t.interval_s == heartbeat.DEFAULT_INTERVAL_S
    assert t.enabled is True


async def test_the_suggested_cadence_is_hours_not_minutes(db):
    """裁决③: OpenClaw ships 30 minutes; this is the user's own machine and
    the user's own tokens, so the suggestion is deliberately slower."""
    assert heartbeat.DEFAULT_INTERVAL_S >= 6 * 3600


async def test_syncing_twice_does_not_create_a_second_task(db):
    await _set(db, heartbeat_enabled="true", heartbeat_checklist="- x")
    await heartbeat.sync_task()
    await heartbeat.sync_task()
    async with db() as s:
        assert len((await s.execute(select(ScheduledTask))).scalars().all()) == 1


async def test_editing_the_checklist_updates_the_existing_task(db):
    await _set(db, heartbeat_enabled="true", heartbeat_checklist="- first")
    await heartbeat.sync_task()
    async with db() as s:
        first = (await s.execute(select(ScheduledTask))).scalars().one()
        first_id = first.id
    async with db() as s:
        row = (await s.execute(select(Setting).where(
            Setting.key == "heartbeat_checklist"))).scalars().one()
        row.value = "- second"
        await s.commit()
    await heartbeat.sync_task()
    async with db() as s:
        task = (await s.execute(select(ScheduledTask))).scalars().one()
    assert task.id == first_id                      # same row, not a duplicate
    assert "second" in task.prompt


async def test_disabling_removes_the_task(db):
    await _set(db, heartbeat_enabled="true", heartbeat_checklist="- x")
    await heartbeat.sync_task()
    async with db() as s:
        row = (await s.execute(select(Setting).where(
            Setting.key == "heartbeat_enabled"))).scalars().one()
        row.value = "false"
        await s.commit()
    await heartbeat.sync_task()
    async with db() as s:
        assert (await s.execute(select(ScheduledTask))).scalars().all() == []


async def test_a_custom_interval_is_honoured_but_floored(db):
    from server.services import scheduler
    await _set(db, heartbeat_enabled="true", heartbeat_checklist="- x",
               heartbeat_interval_s="60")           # below the scheduler's floor
    await heartbeat.sync_task()
    async with db() as s:
        task = (await s.execute(select(ScheduledTask))).scalars().one()
    assert task.interval_s == scheduler.MIN_INTERVAL_S


# ── what the turn is asked to do ──────────────────────────────────────────
def test_the_prompt_carries_the_checklist_and_asks_for_judgement():
    prompt = heartbeat.build_prompt("- watch CI\n- chase invoices")
    assert "watch CI" in prompt and "chase invoices" in prompt
    # It must ask whether anything needs doing, not order it done.
    assert "?" in prompt or "?" in prompt or "判断" in prompt


def test_the_prompt_says_nothing_may_be_the_answer():
    """Without this a model reliably invents work to look useful.

    Asserting on the word 「没有」 alone did NOT discriminate: the framing
    question (「有没有哪一条…」) contains it too, so deleting the permission
    sentence left the test green. Measured, then narrowed to the sentence that
    actually grants the exit."""
    prompt = heartbeat.build_prompt("- x")
    assert "什么都不用做" in prompt
    assert "暂时没有需要处理的" in prompt


def test_the_prompt_does_not_promise_tools_it_will_not_have():
    """A heartbeat runs unattended, so writes and commands are refused. Telling
    it to 'fix' things would produce a turn that narrates failures."""
    prompt = heartbeat.build_prompt("- x").lower()
    for forbidden in ("run_command", "write_file", "edit_file"):
        assert forbidden not in prompt
