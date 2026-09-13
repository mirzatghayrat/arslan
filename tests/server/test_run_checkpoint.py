import asyncio

from sqlalchemy import select

from server.db.models import Run
from server.services import run_recorder, run_reaper


async def test_boot_preserves_last_checkpoint_without_replaying_tools(execution_db, monkeypatch):
    monkeypatch.setattr(run_recorder, "CHECKPOINT_INTERVAL", 0.01)
    recorder = await run_recorder.RunRecorder.start(
        conversation_id="crash", spawn_id=None, spawn_name="Arslan", user_message="task", kind="host")
    emit = recorder.tee(lambda e: None)
    emit({"type": "stream_chunk", "content": "valuable partial result"})
    await recorder._checkpoint_task
    assert await run_reaper.mark_interrupted_runs() == 1
    async with execution_db() as db:
        run = (await db.execute(select(Run))).scalar_one()
    assert run.status == "interrupted"
    assert run.final_output == "valuable partial result"


async def test_pending_checkpoint_cannot_overwrite_final_output(execution_db):
    recorder = await run_recorder.RunRecorder.start(
        conversation_id="finish", spawn_id=None, spawn_name="Arslan", user_message="task", kind="host")
    recorder.tee(lambda e: None)({"type": "stream_chunk", "content": "partial"})
    await recorder.finalize(summary_message_id=None, full_output="complete")
    await asyncio.sleep(0)
    async with execution_db() as db:
        run = (await db.execute(select(Run))).scalar_one()
    assert run.status == "completed" and run.final_output == "complete"
    assert recorder._checkpoint_task.done()
