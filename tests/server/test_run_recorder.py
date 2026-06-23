from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from arslan.llm import usage_sink
from server.db import session as db_session
from server.db.models import ArslanMessage, Base, Run, RunStep
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


async def test_derive_steps_from_event_stream(memdb):
    rec = await run_recorder.RunRecorder.start(
        conversation_id="c1", spawn_id=None, spawn_name="Mermer",
        user_message="查一下天气", route_ms=80,
    )
    emitted = []
    tee = rec.tee(emitted.append)

    tee({"type": "routing", "spawn_id": 1, "spawn_name": "Mermer"})
    tee({"type": "stream_start", "source": "spawn", "spawn_id": 1})
    tee({"type": "tool_call", "tool": "web_search", "args_summary": "{\"q\":\"weather\"}"})
    tee({"type": "tool_result", "tool": "web_search", "ok": True, "summary": "3 results"})

    assert [e["type"] for e in emitted] == ["routing", "stream_start", "tool_call", "tool_result"]

    async with memdb() as db:
        msg = ArslanMessage(conversation_id="c1", role="spawn_summary",
                            content="s", display_content="full output")
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        summary_id = msg.id

    with usage_sink.collecting():
        usage_sink.report(250)
        await rec.finalize(summary_message_id=summary_id, full_output="full output")

    async with memdb() as db:
        run = await db.get(Run, rec.run_id)
        steps = (await db.execute(
            select(RunStep).where(RunStep.run_id == rec.run_id).order_by(RunStep.seq)
        )).scalars().all()
        linked = await db.get(ArslanMessage, summary_id)

    assert run.status == "recorded"
    assert run.task_tokens == 250
    assert run.total_ms is not None and run.total_ms >= 0
    kinds = [s.kind for s in steps]
    assert kinds == ["route", "dispatch", "tool_call"]
    tool_step = steps[2]
    assert tool_step.ref["tool"] == "web_search"
    assert tool_step.ref["ok"] is True
    assert linked.run_id == rec.run_id


async def test_finalize_schedules_scoring(memdb, monkeypatch):
    called = []
    monkeypatch.setattr(run_recorder, "schedule_scoring", lambda run_id: called.append(run_id))
    rec = await run_recorder.RunRecorder.start(
        conversation_id="c1", spawn_id=None, spawn_name="M", user_message="x", route_ms=0)
    rec.tee(lambda e: None)({"type": "routing", "spawn_id": 1, "spawn_name": "M"})
    with usage_sink.collecting():
        await rec.finalize(summary_message_id=None, full_output="")
    assert called == [rec.run_id]


async def test_unpaired_tool_call_is_flushed(memdb):
    rec = await run_recorder.RunRecorder.start(
        conversation_id="c1", spawn_id=None, spawn_name="Mermer",
        user_message="x", route_ms=0)
    tee = rec.tee(lambda e: None)
    tee({"type": "routing", "spawn_id": 1, "spawn_name": "Mermer"})
    tee({"type": "stream_start", "source": "spawn", "spawn_id": 1})
    tee({"type": "tool_call", "tool": "web_search", "args_summary": "{}"})
    # no tool_result, no spawn_meta — error path
    with usage_sink.collecting():
        await rec.finalize(summary_message_id=None, full_output="")
    from sqlalchemy import select
    from server.db.models import RunStep
    async with memdb() as db:
        steps = (await db.execute(
            select(RunStep).where(RunStep.run_id == rec.run_id).order_by(RunStep.seq)
        )).scalars().all()
    kinds = [s.kind for s in steps]
    assert "tool_call" in kinds
    tool = [s for s in steps if s.kind == "tool_call"][0]
    assert tool.ref["ok"] is False
