"""E2: _0028 evolution-real migration + recorder epoch/kind + kind='live' filters.

- upgrade_sync is idempotent and lands runs.kind/epoch/continuation/final_output,
  synthetic_tasks, evolution_attempts, evolution_proposals.base_prompt_sha.
- a legacy run (row present before the migration) backfills to epoch=0 / kind='live'.
- a recorder-created run gets epoch=1 / kind='live'.
- a kind='replay' run never surfaces in the diagnosis catalog nor as a replay_set candidate.
"""
import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.migrations.versions._0028_evolution_real import upgrade_sync
from server.db.models import ArslanMessage, Base, Run, RunEvaluation


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


# --- migration shape + idempotency ------------------------------------------

@pytest.mark.asyncio
async def test_0028_idempotent_columns_and_tables():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(upgrade_sync)
            await conn.run_sync(upgrade_sync)  # second run must be a no-op, not raise

            run_cols = {r[1] for r in await conn.exec_driver_sql("PRAGMA table_info(runs)")}
            assert {"kind", "epoch", "continuation", "final_output"} <= run_cols

            tables = {r[0] for r in await conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            assert "synthetic_tasks" in tables
            assert "evolution_attempts" in tables

            evo_cols = {r[1] for r in await conn.exec_driver_sql(
                "PRAGMA table_info(evolution_proposals)")}
            assert "base_prompt_sha" in evo_cols
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_0028_legacy_run_backfills_epoch_zero():
    """A row that existed BEFORE the migration must backfill to epoch=0 / kind='live'
    (the ADD COLUMN ... DEFAULT clause fills existing rows)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            # legacy runs table (pre-0028 shape — no kind/epoch/continuation/final_output)
            await conn.exec_driver_sql(
                "CREATE TABLE runs (id INTEGER PRIMARY KEY, conversation_id VARCHAR(50) NOT NULL, "
                "user_message TEXT NOT NULL DEFAULT '', status VARCHAR(20), task_tokens INTEGER, "
                "created_at DATETIME)")
            await conn.exec_driver_sql(
                "INSERT INTO runs (conversation_id, status, task_tokens) VALUES ('c1','scored',0)")

            await conn.run_sync(upgrade_sync)

            row = (await conn.exec_driver_sql("SELECT kind, epoch, continuation FROM runs")).fetchone()
            assert row[0] == "live"      # kind DEFAULT 'live'
            assert row[1] == 0           # epoch DEFAULT 0 — pre-baseline quarantine
            assert row[2] == 0           # continuation DEFAULT 0
    finally:
        await engine.dispose()


# --- recorder writes epoch=1 / kind='live' ----------------------------------

@pytest.mark.asyncio
async def test_recorder_start_marks_epoch1_live(memdb, monkeypatch):
    from server.services import run_recorder

    monkeypatch.setattr(run_recorder, "schedule_scoring", lambda _rid: None)
    rec = await run_recorder.RunRecorder.start(
        conversation_id="c1", spawn_id=None, spawn_name="Mermer", user_message="hi")
    async with memdb() as db:
        run = await db.get(Run, rec.run_id)
        assert run.kind == "live"
        assert run.epoch == 1
        assert run.continuation is False


@pytest.mark.asyncio
async def test_recorder_finalize_keeps_epoch1_and_continuation(memdb, monkeypatch):
    from server.services import run_recorder

    monkeypatch.setattr(run_recorder, "schedule_scoring", lambda _rid: None)
    rec = await run_recorder.RunRecorder.start(
        conversation_id="c1", spawn_id=None, spawn_name="Mermer",
        user_message="继续", continuation=True)
    await rec.finalize(summary_message_id=None, full_output="done")
    async with memdb() as db:
        run = await db.get(Run, rec.run_id)
        assert run.kind == "live"
        assert run.epoch == 1
        assert run.continuation is True
        assert run.status == "recorded"


# --- kind='live' filters -----------------------------------------------------

async def _seed_run(Session, *, kind: str, epoch: int, spawn_id: int, spawn_name: str,
                    status: str = "scored", output: str = "out", scored_score: float = 8.0) -> int:
    async with Session() as db:
        run = Run(conversation_id="c1", spawn_id=spawn_id, spawn_name=spawn_name,
                  user_message="task", status=status, task_tokens=5,
                  kind=kind, epoch=epoch, overall_score=scored_score,
                  created_at=datetime.datetime.utcnow())
        db.add(run)
        await db.commit()
        await db.refresh(run)
        db.add(ArslanMessage(conversation_id="c1", role="spawn_summary",
                             content=output, display_content=output, run_id=run.id))
        db.add(RunEvaluation(run_id=run.id, dimension="completion", status="pass", score=scored_score))
        await db.commit()
        return run.id


@pytest.mark.asyncio
async def test_replay_run_is_not_a_replay_set_candidate(memdb):
    from server.services import replay_set

    live_id = await _seed_run(memdb, kind="live", epoch=1, spawn_id=1, spawn_name="Bot")
    await _seed_run(memdb, kind="replay", epoch=1, spawn_id=1, spawn_name="Bot")   # excluded: kind
    await _seed_run(memdb, kind="live", epoch=0, spawn_id=1, spawn_name="Bot")      # excluded: epoch=0

    items = await replay_set.build(1)
    ids = [it["run_id"] for it in items]
    assert ids == [live_id]


@pytest.mark.asyncio
async def test_replay_run_absent_from_catalog(client):
    async with client.db_maker() as db:
        for kind, name in (("live", "LiveBot"), ("replay", "ReplayBot")):
            db.add(Run(conversation_id="c1", spawn_id=(1 if kind == "live" else 2),
                       spawn_name=name, user_message="t", status="recorded",
                       task_tokens=1, kind=kind, epoch=1,
                       created_at=datetime.datetime.utcnow()))
        await db.commit()

    resp = await client.get("/api/v1/runs/catalog?range=1h")
    assert resp.status_code == 200
    body = resp.json()
    assert body["fleet"]["run_count"] == 1
    assert "ReplayBot" not in [s["spawn_name"] for s in body["spawns"]]
