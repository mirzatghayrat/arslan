from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


async def test_finalize_persists_detail_and_merges_trace(memdb, monkeypatch):
    from server.services import run_recorder
    from server.orchestrator import run_trace
    from server.db.models import Run, RunStep

    monkeypatch.setattr(run_recorder, "schedule_scoring", lambda rid: None)

    rec = await run_recorder.RunRecorder.start(
        conversation_id="c", spawn_id=None, spawn_name="S", user_message="hi")
    # feed one tool_call + tool_result event so a tool_call step is derived, and a run_trace entry
    rec._events = [
        (datetime.utcnow(), {"type": "tool_call", "tool": "web_search", "args_summary": "{\"query\":\"q\"}"}),
        (datetime.utcnow(), {"type": "tool_result", "tool": "web_search", "ok": True, "summary": "5 results"}),
    ]
    with run_trace.collecting():
        run_trace.record(tool="web_search", args={"query": "q"}, result="RAWRESULT",
                          ok=True, error=None, ms=9)
        rid = await rec.finalize(
            summary_message_id=None, full_output="OUT",
            model="gpt-x", provider="openai", tokens_in=3, tokens_out=4, tokens_estimated=False,
            error_kind=None, error_text=None, system_prompt="SYS", injected_kb="KB")

    async with memdb() as db:
        run = await db.get(Run, rid)
        assert run.model == "gpt-x" and run.provider == "openai"
        assert run.tokens_in == 3 and run.tokens_out == 4 and run.tokens_estimated is False
        assert run.system_prompt == "SYS" and run.injected_kb == "KB"
        steps = (await db.execute(select(RunStep).where(RunStep.run_id == rid))).scalars().all()
        tool_steps = [s for s in steps if s.kind == "tool_call"]
        assert tool_steps and tool_steps[0].detail.get("args_full") is not None
        assert tool_steps[0].detail.get("result_raw") == "RAWRESULT"
        assert tool_steps[0].ref.get("ok") is True


async def test_finalize_truncates_error_text(memdb, monkeypatch):
    from server.services import run_recorder
    from server.db.models import Run

    monkeypatch.setattr(run_recorder, "schedule_scoring", lambda rid: None)
    rec = await run_recorder.RunRecorder.start(
        conversation_id="c", spawn_id=None, spawn_name="S", user_message="hi")
    long_err = "E" * (run_recorder.RUN_ERR_CAP + 500)
    rid = await rec.finalize(summary_message_id=None, full_output="", error_kind="timeout",
                              error_text=long_err)
    async with memdb() as db:
        run = await db.get(Run, rid)
        assert run.error_kind == "timeout"
        assert len(run.error_text) == run_recorder.RUN_ERR_CAP


async def test_finalize_backward_compatible_defaults(memdb, monkeypatch):
    """Existing callers passing only summary_message_id + full_output must still work."""
    from server.services import run_recorder
    from server.db.models import Run

    monkeypatch.setattr(run_recorder, "schedule_scoring", lambda rid: None)
    rec = await run_recorder.RunRecorder.start(
        conversation_id="c", spawn_id=None, spawn_name="S", user_message="hi")
    rid = await rec.finalize(summary_message_id=None, full_output="OUT")
    async with memdb() as db:
        run = await db.get(Run, rid)
        assert run.model is None and run.provider is None
        assert run.tokens_estimated is False
