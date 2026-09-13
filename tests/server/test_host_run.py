"""Host and spawn execution share real Run storage and cancellation semantics."""
import asyncio

import pytest
from sqlalchemy import select

from arslan.llm import usage_sink
from server.db.models import Run, RunStep
from server.services import execution_context, host_run, run_recorder, run_registry

pytestmark = pytest.mark.asyncio


async def test_host_run_persists_trace_usage_and_output(execution_db, monkeypatch):
    judged = []
    monkeypatch.setattr(run_recorder, "schedule_scoring", judged.append)
    events = []

    async def body(emit):
        assert execution_context.current_run_id() is not None
        emit({"type": "stream_start", "source": "arslan"})
        emit({"type": "tool_call", "tool": "run_python", "args": {}})
        emit({"type": "tool_result", "tool": "run_python", "ok": True, "result": "42"})
        emit({"type": "stream_chunk", "content": "answer"})
        usage_sink.report(30)
        usage_sink.report_detail(tokens_in=20, tokens_out=10, model="test", provider="test")
        emit({"type": "stream_end", "message_id": None})
        return "answer"

    assert await host_run.execute("host-test", "question", events.append, body) == "answer"
    async with execution_db() as db:
        run = (await db.execute(select(Run))).scalar_one()
        steps = (await db.execute(select(RunStep))).scalars().all()
    assert run.kind == "host" and run.status == "completed"
    assert run.final_output == "answer" and run.task_tokens == 30
    assert (run.tokens_in, run.tokens_out) == (20, 10)
    assert len([e for e in events if e["type"] == "stream_start"]) == 1
    assert all(e["run_id"] == run.id for e in events)
    assert steps and not judged
    assert not run_registry.active_for("host-test")
    assert execution_context.current_run_id() is None


async def test_host_cancel_preserves_partial_and_caller(execution_db):
    entered = asyncio.Event()
    events = []

    async def body(emit):
        emit({"type": "stream_chunk", "content": "partial"})
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(host_run.execute("host-cancel", "question", events.append, body))
    await entered.wait()
    run_id = run_registry.active_for("host-cancel")[0]
    snapshot = run_registry.journal_snapshots("host-cancel")[0][1]
    assert snapshot[0]["run_id"] == run_id
    assert run_registry.cancel(run_id)
    assert await asyncio.wait_for(task, 2) is None
    async with execution_db() as db:
        run = await db.get(Run, run_id)
    assert run.status == "cancelled" and run.final_output == "partial"
    assert events[-1] == {"type": "run_cancelled", "run_id": run_id}
    assert not run_registry.active_for("host-cancel")


async def test_outer_cancel_is_not_swallowed(execution_db):
    entered = asyncio.Event()

    async def body(emit):
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(host_run.execute("outer-cancel", "question", lambda ev: None, body))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not run_registry.active_for("outer-cancel")
