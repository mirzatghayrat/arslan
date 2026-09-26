from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from server.db.models import Run, RunEvaluation
from server.services import personal_context, replay_run, run_eval_service, run_recorder, run_reaper


@pytest.mark.parametrize("flags", [
    {"no_learning": True, "cloud_memory_allowed": True},
    {"cloud_memory_allowed": False},
    {"model_is_local": True, "cloud_memory_allowed": True},
    {"temporary": True, "cloud_memory_allowed": True},
])
async def test_privacy_survives_detached_recording_and_background_reuse(execution_db, monkeypatch, flags):
    def forbidden(*args, **kwargs):
        raise AssertionError("Private turns must never invoke a judge or scheduler")
    monkeypatch.setattr(run_eval_service, "build_adapter", forbidden)
    monkeypatch.setattr(run_recorder, "schedule_scoring", forbidden)
    with personal_context.bind(personal_context.TaskMemoryContext(task_id="task", run_id="attempt", **flags)):
        recorder = await run_recorder.RunRecorder.start(
            conversation_id="private", spawn_id=None, spawn_name=None, user_message="private input")
    async with execution_db() as db:
        row = await db.get(Run, recorder.run_id)
        assert row.no_learning
        row.status = "recorded"
        row.created_at = datetime.utcnow() - timedelta(hours=1)
        await db.commit()
        assert not await replay_run.is_replayable(db, row.id)
    assert await run_reaper._reaper_candidates() == []
    await run_eval_service.score(recorder.run_id)
    async with execution_db() as db:
        assert (await db.execute(select(RunEvaluation))).scalars().all() == []
        assert (await db.get(Run, recorder.run_id)).status == "recorded"


async def test_restore_privacy_migration_is_idempotent_for_old_archives():
    from sqlalchemy import create_engine
    from server.db.migrations.versions._0050_run_privacy import upgrade_sync
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE runs (id INTEGER PRIMARY KEY)")
        db.exec_driver_sql("INSERT INTO runs VALUES (1),(2)")
        db.exec_driver_sql("CREATE TABLE memory_restore_sources(source_kind TEXT,source_id TEXT)")
        db.exec_driver_sql("INSERT INTO memory_restore_sources VALUES ('run_id','1')")
        upgrade_sync(db)
        upgrade_sync(db)
        assert db.exec_driver_sql("SELECT no_learning FROM runs ORDER BY id").scalars().all() == [1, 0]
    engine.dispose()
