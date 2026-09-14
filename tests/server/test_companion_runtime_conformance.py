"""Real host/dispatcher/recipe entry points, synthetic models and tool executors."""
import asyncio

import pytest
from sqlalchemy import select

from arslan.execution_budget import current
from arslan.models import LLMResponse
from server.db.models import RecipeExecution, RecipeVersion, Run, RunStep, Spawn
from server.orchestrator import arslan, dispatcher, memory, spawn_loop, tool_loop
from server.orchestrator.tool_caller import current_caller
from server.services import host_run, knowledge, recipes, run_registry


@pytest.fixture
async def runtime_case(execution_db, monkeypatch):
    tool = {"key": "fixture_read", "description": "Read synthetic evidence"}
    async with execution_db() as db:
        db.add(Spawn(id=1, name="Fixture Expert", domain_category="test", system_prompt="Fixture"))
        version = RecipeVersion(key="fixture", version=1, name="Fixture", spec={
            "name": "Fixture", "max_parallel": 1,
            "steps": [{"key": "read", "name": "Read", "spawn_id": 1, "task": "Read fixture"}],
        })
        db.add(version)
        await db.flush()
        db.add(RecipeExecution(id=1, request_key="fixture", recipe_id=version.id,
                               input="Fixture", status="queued", checkpoint={}))
        await db.commit()

    async def context(*args, **kwargs):
        return {"history": [{"role": "user", "content": "Read fixture"}], "summary": ""}
    async def facts(*args, **kwargs):
        return ""
    async def retrieve(*args, **kwargs):
        return []
    async def tools(*args, **kwargs):
        return [tool]
    async def system(*args, **kwargs):
        return "Fixture system", [tool]
    monkeypatch.setattr(memory, "assemble_working_context", context)
    monkeypatch.setattr(memory, "facts_text", facts)
    monkeypatch.setattr(knowledge, "retrieve_scoped", retrieve)
    monkeypatch.setattr(arslan, "_team_roster", facts)
    monkeypatch.setattr(arslan, "_arslan_tools", tools)
    monkeypatch.setattr(dispatcher, "build_spawn_system", system)
    monkeypatch.setattr(spawn_loop, "wired_tools_for_spawn", tools)

    async def run(entry, events):
        if entry == "host":
            return await arslan._handle_answer("fixture-host", "Read fixture", events.append)
        if entry == "worker":
            async def body(sink):
                result = await dispatcher.dispatch(
                    "fixture-worker", spawn_id=1, task_brief="Read fixture",
                    on_event=sink, on_chunk=lambda text: sink({"type": "stream_chunk", "content": text}),
                    include_history=False, persist=False,
                )
                return result["full_output"]
            return await host_run.execute("fixture-worker", "Read fixture", events.append, body,
                                          kind="host", name="Fixture Expert")
        await recipes.execute(1)
        async with execution_db() as db:
            row = await db.get(RecipeExecution, 1)
            return row.checkpoint["steps"]["read"].get("output")
    return run


@pytest.mark.parametrize("entry", ["host", "worker", "recipe"])
@pytest.mark.parametrize("allowed", [True, False])
async def test_actual_entries_share_pretool_gate_and_persisted_results(
    entry, allowed, runtime_case, execution_db, monkeypatch,
):
    observed = []
    class Adapter:
        def __init__(self):
            self.calls = 0
        async def chat(self, system, user, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(content="", usage={}, tool_calls=[{
                    "id": "one", "type": "function",
                    "function": {"name": "fixture_read" if allowed else "not_granted", "arguments": {}},
                }])
            assert "TOOL RESULT" in user
            return LLMResponse(content="Fixture result.", usage={}, tool_calls=[])
    adapter = Adapter()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    class Executor:
        async def execute(self, args):
            observed.append((current().id, current_caller().actor))
            return {"ok": True, "external": False, "summary": "verified fixture"}
    monkeypatch.setitem(tool_loop.EXECUTORS, "fixture_read", Executor())
    events = []
    assert await runtime_case(entry, events) == "Fixture result."
    assert len(observed) == int(allowed)
    if allowed:
        assert observed[0][1] == ("host" if entry == "host" else "spawn")
    async with execution_db() as db:
        runs = (await db.execute(select(Run))).scalars().all()
        steps = (await db.execute(select(RunStep))).scalars().all()
    assert runs and all(row.status == "completed" for row in runs)
    assert steps  # Actual RunRecorder persistence, not a test-only event list.
    assert adapter.calls == 2
    assert current_caller() is None


@pytest.mark.parametrize("entry", ["host", "worker", "recipe"])
async def test_actual_entries_propagate_outer_cancellation(entry, runtime_case, execution_db, monkeypatch):
    entered = asyncio.Event()
    stopped = asyncio.Event()
    class Adapter:
        async def chat(self, system, user, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: Adapter())
    task = asyncio.create_task(runtime_case(entry, []))
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 3)
    assert stopped.is_set()
    async with execution_db() as db:
        runs = (await db.execute(select(Run))).scalars().all()
    assert runs and all(row.status == "cancelled" for row in runs)
    assert all(not run_registry.active_for(row.conversation_id) for row in runs)


@pytest.mark.parametrize("tool_name,callback_name,args", [
    ("write_file", "confirm_workspace_write", {"path": "fixture.txt", "content": "fixture"}),
    ("schedule_task", "confirm_schedule", {"name": "fixture", "when": "tomorrow"}),
])
async def test_native_loop_passes_explicit_confirmation_callbacks(tool_name, callback_name, args, monkeypatch):
    approved, executed = [], []
    class Adapter:
        def __init__(self):
            self.calls = 0
        async def chat(self, system, user, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(content="", usage={}, tool_calls=[{
                    "id": "one", "function": {"name": tool_name, "arguments": args},
                }])
            return LLMResponse(content="Fixture result.", usage={})
    class Executor:
        async def execute(self, args):
            assert approved
            executed.append(args)
            return {"ok": True, "external": False}
    async def approve(*args):
        approved.append(args)
        return True
    async def resolve():
        return [{"key": tool_name, "description": "Fixture"}]
    adapter = Adapter()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    monkeypatch.setitem(tool_loop.EXECUTORS, tool_name, Executor())
    await tool_loop.run_native(system="Fixture", user_content="Fixture", history=[],
                               emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=resolve,
                               **{callback_name: approve})
    assert len(approved) == len(executed) == 1
