import asyncio

from sqlalchemy import func, select

from arslan.models import LLMResponse
from server.db.models import ArslanMessage, ArslanSummary, ConversationEvent, MemoryEntry, Run, RunStep, UsageLedger
from server.orchestrator import arslan, tool_loop
from server.services import personal_context as pc, run_registry, temporary_turn


async def test_temporary_uses_native_but_writes_no_transcript_or_runs(execution_db, monkeypatch):
    requests = []
    class Adapter:
        async def chat(self, system, user, **kwargs):
            requests.append((system, user, kwargs))
            return LLMResponse(content="Temporary reply", usage={}, tool_calls=[])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: Adapter())
    events = []
    with pc.bind(pc.TaskMemoryContext(task_id="temp-task", run_id="temp-run", temporary=True)):
        await arslan.handle_user_message("temp-conversation", "Temporary private input", events.append)
    assert len(requests) == 1
    assert not requests[0][2].get("tools")
    assert any(event["type"] == "stream_end" for event in events)
    async with execution_db() as db:
        for model in (ArslanMessage, ArslanSummary, ConversationEvent, MemoryEntry, Run, RunStep, UsageLedger):
            assert await db.scalar(select(func.count()).select_from(model)) == 0
    assert temporary_turn.history("temp-conversation")[-1]["content"] == "Temporary reply"
    temporary_turn.clear("temp-conversation")
    assert temporary_turn.history("temp-conversation") == []


async def test_temporary_cancel_has_no_recovery_record(execution_db, monkeypatch):
    entered = asyncio.Event()
    class Adapter:
        async def chat(self, system, user, **kwargs):
            entered.set()
            await asyncio.Event().wait()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: Adapter())
    events = []
    with pc.bind(pc.TaskMemoryContext(task_id="temp-task", run_id="temp-run", temporary=True)):
        task = asyncio.create_task(arslan.handle_user_message("temp-cancel", "Wait", events.append))
        await asyncio.wait_for(entered.wait(), 2)
        temporary_turn.clear("temp-cancel")
        await asyncio.wait_for(task, 2)
    assert any(event["type"] == "run_cancelled" for event in events)
    assert run_registry.active_for("temp-cancel") == []
    assert temporary_turn.history("temp-cancel") == []


async def test_temporary_forged_tool_is_not_executed(execution_db, monkeypatch):
    calls = []
    class Executor:
        async def execute(self, args):
            calls.append(args)
            return {"ok": True}
    class Adapter:
        count = 0
        async def chat(self, system, user, **kwargs):
            self.count += 1
            if self.count == 1:
                return LLMResponse(content="", usage={}, tool_calls=[{
                    "id": "forged", "type": "function",
                    "function": {"name": "write_file", "arguments": {"content": "secret"}},
                }])
            return LLMResponse(content="Cannot write in temporary mode.", usage={}, tool_calls=[])
    adapter = Adapter()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    monkeypatch.setitem(tool_loop.EXECUTORS, "write_file", Executor())
    with pc.bind(pc.TaskMemoryContext(task_id="temp-task", run_id="temp-run", temporary=True)):
        await arslan.handle_user_message("temp-forged", "Write a file", lambda _: None)
    assert calls == []
    assert adapter.count == 2
    temporary_turn.clear("temp-forged")
