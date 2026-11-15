import pytest

from server.db.models import Run
from server.services import personal_context, run_recorder


@pytest.mark.parametrize("flags", [
    {"no_learning": True, "cloud_memory_allowed": True},
    {"cloud_memory_allowed": False},
    {"model_is_local": True, "cloud_memory_allowed": True},
    {"temporary": True, "cloud_memory_allowed": True},
])
async def test_privacy_survives_detached_recording_and_background_reuse(execution_db, flags):
    # C7c-5a: the judge and the stuck-run reaper (the background reusers this guarded
    # against) are gone; the immutable per-attempt ceiling is still recorded on the row.
    with personal_context.bind(personal_context.TaskMemoryContext(task_id="task", run_id="attempt", **flags)):
        recorder = await run_recorder.RunRecorder.start(
            conversation_id="private", spawn_id=None, spawn_name=None, user_message="private input")
    async with execution_db() as db:
        row = await db.get(Run, recorder.run_id)
        assert row.no_learning


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
