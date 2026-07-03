"""run_command executions are captured by the run audit trail.

run_command emits the SAME generic tool_call/tool_result WS frames that every
other tool emits (via tool_loop's _dispatch_tool -> _record_tool_result), so the
run recorder's _derive_steps pairs them into a RunStep with tool="run_command"
without any run_command-specific handling. This confirms that.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from arslan.llm import usage_sink
from server.db import session as db_session
from server.db.models import Base, Run, RunStep
from server.services import run_recorder


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    monkeypatch.setattr(run_recorder, "schedule_scoring", lambda run_id: None)
    yield Session


async def test_run_command_execution_recorded_as_runstep(memdb):
    rec = await run_recorder.RunRecorder.start(
        conversation_id="c1", spawn_id=None, spawn_name="Mermer",
        user_message="run the tests", route_ms=40,
    )
    tee = rec.tee(lambda e: None)

    tee({"type": "routing", "spawn_id": 1, "spawn_name": "Mermer"})
    tee({"type": "stream_start", "source": "spawn", "spawn_id": 1})
    tee({"type": "tool_call", "tool": "run_command",
         "args_summary": "{\"command\":\"pytest -q\"}"})
    tee({"type": "tool_result", "tool": "run_command", "ok": True,
         "summary": "exit=0, 3 passed"})

    with usage_sink.collecting():
        await rec.finalize(summary_message_id=None, full_output="done")

    async with memdb() as db:
        steps = (await db.execute(
            select(RunStep).where(RunStep.run_id == rec.run_id).order_by(RunStep.seq)
        )).scalars().all()
        run = await db.get(Run, rec.run_id)

    assert run.status == "recorded"

    tool_steps = [s for s in steps if s.kind == "tool_call"]
    assert len(tool_steps) == 1
    step = tool_steps[0]
    assert step.ref["tool"] == "run_command"
    assert step.ref["ok"] is True
    assert step.detail["args_summary"] == "{\"command\":\"pytest -q\"}"
    assert step.detail["summary"] == "exit=0, 3 passed"


async def test_failed_run_command_recorded_with_ok_false(memdb):
    rec = await run_recorder.RunRecorder.start(
        conversation_id="c1", spawn_id=None, spawn_name="Mermer",
        user_message="run the build", route_ms=0,
    )
    tee = rec.tee(lambda e: None)

    tee({"type": "routing", "spawn_id": 1, "spawn_name": "Mermer"})
    tee({"type": "stream_start", "source": "spawn", "spawn_id": 1})
    tee({"type": "tool_call", "tool": "run_command",
         "args_summary": "{\"command\":\"make build\"}"})
    tee({"type": "tool_result", "tool": "run_command", "ok": False,
         "summary": "exit=2, command not allowed"})

    with usage_sink.collecting():
        await rec.finalize(summary_message_id=None, full_output="")

    async with memdb() as db:
        steps = (await db.execute(
            select(RunStep).where(RunStep.run_id == rec.run_id).order_by(RunStep.seq)
        )).scalars().all()

    tool_steps = [s for s in steps if s.kind == "tool_call"]
    assert len(tool_steps) == 1
    assert tool_steps[0].ref["tool"] == "run_command"
    assert tool_steps[0].ref["ok"] is False
