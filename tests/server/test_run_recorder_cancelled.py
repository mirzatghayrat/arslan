"""S3-M1 Task 2: finalize(status_override=) — cancelled/interrupted terminal states
must never schedule judge scoring (only scoring produces status='scored', and
replay_set only collects status='scored', so an unscored run can never enter the
evolution corpus)."""

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from arslan.llm import usage_sink
from server.db import session as db_session
from server.db.models import Base, Run, RunStep, Spawn
from server.services import run_recorder


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


async def _seed_spawn(Session) -> int:
    async with Session() as db:
        spawn = Spawn(name="S", domain_category="general", system_prompt="sp")
        db.add(spawn)
        await db.commit()
        await db.refresh(spawn)
        return spawn.id


async def test_finalize_status_override_skips_scoring(memdb, monkeypatch):
    scheduled: list[int] = []
    monkeypatch.setattr(run_recorder, "schedule_scoring", scheduled.append)
    spawn_id = await _seed_spawn(memdb)

    rec = await run_recorder.RunRecorder.start(
        conversation_id="c-cancel", spawn_id=spawn_id, spawn_name="S",
        user_message="u")
    with usage_sink.collecting():
        await rec.finalize(summary_message_id=None, full_output="partial text",
                           status_override="cancelled")

    async with memdb() as db:
        run = (await db.execute(select(Run).where(Run.id == rec.run_id))).scalar_one()
    assert run.status == "cancelled"
    assert run.kind == "live"
    assert scheduled == []  # cancelled runs are never judge-scored → never corpus
    # Diagnostics row-completeness contract: overridden runs still finalize fully.
    assert run.ended_at is not None
    assert run.total_ms is not None


async def test_finalize_is_idempotent(memdb, monkeypatch):
    """Review I1: a cancel landing during a finalize await (post-commit) re-enters
    finalize via the cancel handler. The second call must short-circuit — no duplicated
    RunStep rows, and the already-written terminal status must NOT flip."""
    scheduled: list[int] = []
    monkeypatch.setattr(run_recorder, "schedule_scoring", scheduled.append)
    spawn_id = await _seed_spawn(memdb)

    rec = await run_recorder.RunRecorder.start(
        conversation_id="c-idem", spawn_id=spawn_id, spawn_name="S",
        user_message="u")
    tee = rec.tee(lambda ev: None)
    tee({"type": "routing", "spawn_id": spawn_id, "spawn_name": "S"})
    with usage_sink.collecting():
        await rec.finalize(summary_message_id=None, full_output="done")
        await rec.finalize(summary_message_id=None, full_output="",
                           status_override="cancelled")

    async with memdb() as db:
        run = (await db.execute(select(Run).where(Run.id == rec.run_id))).scalar_one()
        steps = (await db.execute(select(RunStep).where(
            RunStep.run_id == rec.run_id))).scalars().all()
    assert run.status == "recorded"          # second finalize did not flip the status
    assert len(steps) == 1                   # step rows written exactly once
    assert scheduled == [rec.run_id]         # scoring scheduled exactly once


async def test_precommit_cancel_allows_refinalize(memdb, monkeypatch):
    """Review I1 residual: a cancel landing DURING finalize's pre-commit awaits rolls
    the write back — the latch must clear so the cancel handler's re-entrant
    finalize(status_override='cancelled') runs against the rolled-back state instead
    of short-circuiting (which would rot the row at 'recording' AFTER a run_cancelled
    frame already went out)."""
    scheduled: list[int] = []
    monkeypatch.setattr(run_recorder, "schedule_scoring", scheduled.append)
    spawn_id = await _seed_spawn(memdb)

    rec = await run_recorder.RunRecorder.start(
        conversation_id="c-precommit", spawn_id=spawn_id, spawn_name="S",
        user_message="u")
    tee = rec.tee(lambda ev: None)
    tee({"type": "routing", "spawn_id": spawn_id, "spawn_name": "S"})

    calls = {"n": 0}
    real_maker = db_session.AsyncSessionLocal

    def cancelling_maker():
        session = real_maker()
        real_commit = session.commit

        async def commit_cancelled_once():
            calls["n"] += 1
            if calls["n"] == 1:
                raise asyncio.CancelledError
            await real_commit()

        session.commit = commit_cancelled_once
        return session

    monkeypatch.setattr(db_session, "AsyncSessionLocal", cancelling_maker)

    with usage_sink.collecting():
        with pytest.raises(asyncio.CancelledError):
            await rec.finalize(summary_message_id=None, full_output="done")
        # The cancel handler's second finalize must NOT short-circuit.
        await rec.finalize(summary_message_id=None, full_output="",
                           status_override="cancelled")

    async with memdb() as db:
        run = (await db.execute(select(Run).where(Run.id == rec.run_id))).scalar_one()
        steps = (await db.execute(select(RunStep).where(
            RunStep.run_id == rec.run_id))).scalars().all()
    assert run.status == "cancelled"     # re-finalize landed, row is not rotting
    assert len(steps) == 1               # first attempt rolled back — no duplicates
    assert scheduled == []               # cancelled runs are never scored


async def test_postcommit_cancel_does_not_refinalize(memdb, monkeypatch):
    """Final review: a cancel delivered during the POST-commit session close must NOT
    release the latch — the commit already landed, so a re-entrant
    finalize(status_override='cancelled') would flip a real terminal status, duplicate
    RunStep rows, and let the cancel handler persist a duplicate 已中断 partial."""
    scheduled: list[int] = []
    monkeypatch.setattr(run_recorder, "schedule_scoring", scheduled.append)
    spawn_id = await _seed_spawn(memdb)

    rec = await run_recorder.RunRecorder.start(
        conversation_id="c-postcommit", spawn_id=spawn_id, spawn_name="S",
        user_message="u")
    tee = rec.tee(lambda ev: None)
    tee({"type": "routing", "spawn_id": spawn_id, "spawn_name": "S"})

    closes = {"n": 0}
    real_maker = db_session.AsyncSessionLocal

    def close_cancelling_maker():
        session = real_maker()
        real_close = session.close

        async def close_cancelled_once():
            closes["n"] += 1
            await real_close()
            if closes["n"] == 1:
                raise asyncio.CancelledError

        session.close = close_cancelled_once
        return session

    monkeypatch.setattr(db_session, "AsyncSessionLocal", close_cancelling_maker)

    with usage_sink.collecting():
        with pytest.raises(asyncio.CancelledError):
            await rec.finalize(summary_message_id=None, full_output="done")
        # Commit landed before the cancel — the re-entrant call must SHORT-CIRCUIT.
        await rec.finalize(summary_message_id=None, full_output="",
                           status_override="cancelled")

    async with memdb() as db:
        run = (await db.execute(select(Run).where(Run.id == rec.run_id))).scalar_one()
        steps = (await db.execute(select(RunStep).where(
            RunStep.run_id == rec.run_id))).scalars().all()
    assert run.status == "recorded"      # committed terminal status never flips
    assert len(steps) == 1               # no duplicated step rows
    assert rec._finalized is True        # latch held — arslan.py's handler keys off this


async def test_finalize_without_override_still_schedules_scoring(memdb, monkeypatch):
    """Regression guard: the normal live path is unchanged by the new parameter."""
    scheduled: list[int] = []
    monkeypatch.setattr(run_recorder, "schedule_scoring", scheduled.append)
    spawn_id = await _seed_spawn(memdb)

    rec = await run_recorder.RunRecorder.start(
        conversation_id="c-normal", spawn_id=spawn_id, spawn_name="S",
        user_message="u")
    with usage_sink.collecting():
        await rec.finalize(summary_message_id=None, full_output="done")

    async with memdb() as db:
        run = (await db.execute(select(Run).where(Run.id == rec.run_id))).scalar_one()
    assert run.status == "recorded"
    assert scheduled == [rec.run_id]
