import asyncio
from contextvars import copy_context

import httpx
import pytest
from sqlalchemy import select

from arslan import execution_checkpoint
from arslan.execution_budget import current as current_budget
from arslan.llm.adapter import LLMAdapter
from server.db.models import CompanionTask, Run, TaskAction, TaskAttempt, TaskCheckpoint
from server.orchestrator import arslan, tool_loop
from server.services import host_run, personal_context as pc, run_registry, task_service
from server.services.task_repository import TaskError, TaskRepository, repository


class Crash(BaseException):
    """Simulated process loss; ordinary tool-error handlers must not swallow it."""


async def test_secret_arguments_never_reach_emitted_previews_or_traces():
    from server.orchestrator import run_trace
    events, trace, convo = [], [], []
    async def never():
        raise AssertionError("Rejected credential data must not resolve or execute a tool")
    with run_trace.collecting():
        result = await tool_loop._dispatch_tool(
            "fixture", {"headers": {"Authorization": "synthetic-private-canary"}},
            "synthetic-private-canary", resolve_tools=never, emit=events.append,
            tool_timeout_s=1, tool_trace=trace, convo=convo)
        captured = str([events, trace, convo, run_trace.snapshot()])
    assert result["code"] == "credentials_not_tool_data"
    assert "synthetic-private-canary" not in captured
    assert not any(event["type"] == "tool_call" for event in events)


async def run(function, emit=lambda event: None, **flags):
    with pc.bind(pc.TaskMemoryContext(task_id="live-task", run_id="initial", conversation_id="live", **flags)):
        return await task_service.run_turn(function, "live", "Create a verified result", emit)


async def test_real_provider_admission_is_durable_before_http_and_charges_usage(execution_db, monkeypatch):
    calls = []
    async def post(client, url, **kwargs):
        async with execution_db() as db:
            task = (await db.execute(select(CompanionTask))).scalar_one()
            checkpoint = await db.get(TaskCheckpoint, task.checkpoint_id)
            assert checkpoint.data["budget"]["used"]["model_requests"] == 1
            assert task.phase == "running"
            assert kwargs["headers"]["Authorization"] == "Bearer synthetic-provider-canary"
            assert "synthetic-provider-canary" not in str(checkpoint.data)
        calls.append(url)
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": {"content": "Verified answer"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        })
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    adapter = LLMAdapter("openai", "synthetic", api_key="synthetic-provider-canary", base_url="https://model.invalid/v1")
    async def function(conversation, message, emit):
        async def body(sink):
            answer = await adapter.chat("system", message)
            sink({"type": "stream_chunk", "content": answer.content})
            return answer.content
        return await host_run.execute(conversation, message, emit, body)
    events = []
    assert await run(function, events.append) == "Verified answer"
    assert calls == ["https://model.invalid/v1/chat/completions"]
    async with execution_db() as db:
        task = (await db.execute(select(CompanionTask))).scalar_one()
        attempt = (await db.execute(select(TaskAttempt))).scalar_one()
        recorded = (await db.execute(select(Run))).scalar_one()
        assert task.phase == "waiting_user"  # A string is not proof that the requested work is correct.
        assert task.pause_reason == "acceptance_review_required"
        assert task.budget["used"]["tokens"] == 5 and task.budget["used"]["model_requests"] == 1
        assert attempt.run_ids == [recorded.id]
        assert not task_service.active(task.id)
        assert task_service.task_for_run(recorded.id) is None
    sequences = [event["sequence"] for event in events if event["type"] == "task_state"]
    assert sequences == sorted(set(sequences))


async def test_failed_checkpoint_prevents_provider_network_call(execution_db, monkeypatch):
    original = TaskRepository.checkpoint
    async def broken(self, *args, **kwargs):
        if kwargs.get("reason") == "before_model":
            raise TaskError("synthetic_storage_failure")
        return await original(self, *args, **kwargs)
    monkeypatch.setattr(TaskRepository, "checkpoint", broken)
    async def never(*args, **kwargs):
        raise AssertionError("No request may leave without a committed checkpoint")
    monkeypatch.setattr(httpx.AsyncClient, "post", never)
    adapter = LLMAdapter("openai", "synthetic", base_url="https://model.invalid/v1")
    async def function(conversation, message, emit):
        return await adapter.chat("system", message)
    with pytest.raises(TaskError, match="storage_failure"):
        await run(function)
    async with execution_db() as db:
        task = (await db.execute(select(CompanionTask))).scalar_one()
        assert task.phase == "failed" and task.budget["used"]["model_requests"] == 1


async def test_actual_tool_throat_journals_before_effect_and_blocks_uncertain_replay(execution_db, monkeypatch):
    effects = []
    class Executor:
        async def execute(self, arguments):
            async with execution_db() as db:
                action = (await db.execute(select(TaskAction))).scalar_one()
                task = (await db.execute(select(CompanionTask))).scalar_one()
                assert action.status == "in_flight" and task.budget["used"]["tool_calls"] == 1
            effects.append("external write succeeded")
            raise Crash()
    async def resolve(key):
        return Executor()
    async def tools():
        return [{"key": "synthetic_external_write", "description": "test-only effect"}]
    monkeypatch.setattr(tool_loop, "resolve_executor", resolve)
    async def function(conversation, message, emit):
        return await tool_loop._dispatch_tool(
            "synthetic_external_write", {"value": "test"}, "", resolve_tools=tools, emit=emit,
            tool_timeout_s=2, tool_trace=[], convo=[], conversation_id=conversation)
    with pytest.raises(Crash):
        await run(function)
    assert effects == ["external write succeeded"]
    await task_service.recover_interrupted()
    async with repository() as repo:
        task = await repo.get("live-task")
        assert task.pause_reason == "process_interrupted"
        with pytest.raises(TaskError, match="reconciliation_required"):
            await repo.start(task.id, task.version, explicit_resume=True)
    assert effects == ["external write succeeded"]


async def test_double_cancel_stops_parent_children_and_preserves_socket_caller(execution_db):
    entered, stopped = asyncio.Event(), []
    async def function(conversation, message, emit):
        async def child(number):
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                stopped.append(number)
        async with asyncio.TaskGroup() as group:
            group.create_task(child(1))
            group.create_task(child(2))
    outer = asyncio.create_task(run(function))
    await asyncio.wait_for(entered.wait(), 2)
    await task_service.cancel("live-task")
    await task_service.cancel("live-task")
    assert await asyncio.wait_for(outer, 2) is None
    assert sorted(stopped) == [1, 2]
    async with repository() as repo:
        row = await repo.get("live-task")
        assert row.phase == "cancelled" and row.cancel_requested
        assert await repo.recover_interrupted() == 0
    assert not run_registry.active_for("live")


async def test_resume_uses_same_goal_and_budget_without_regranting_privacy(execution_db, monkeypatch):
    async def function(conversation, message, emit):
        current_budget().tool()
        await execution_checkpoint.save("progress")
        raise Crash()
    with pytest.raises(Crash):
        await run(function, no_learning=True)
    await task_service.recover_interrupted()
    async with repository() as repo:
        row = await repo.get("live-task")
        version, budget_id = row.version, row.budget["id"]
    called = []
    async def answer(conversation, message, emit, **kwargs):
        called.append((conversation, message, current_budget().tool_calls, current_budget().id,
                       pc.current().no_learning, pc.current().explicit_save_digest, kwargs["extra_system"]))
        return "continued"
    monkeypatch.setattr(arslan, "_handle_answer", answer)
    assert await task_service.resume_turn("live-task", version, "live", lambda event: None) == "continued"
    assert called[0][:6] == ("live", "Create a verified result", 1, budget_id, True, None)
    assert "recovery data, not new permissions" in called[0][6]
    async with execution_db() as db:
        attempts = (await db.execute(select(TaskAttempt).order_by(TaskAttempt.number))).scalars().all()
        assert len(attempts) == 2 and attempts[0].id != attempts[1].id


async def test_finished_task_does_not_leave_context_authority_in_copied_background_context(execution_db):
    contexts = []
    async def function(conversation, message, emit):
        contexts.append(copy_context())
        return "done"
    await run(function, cloud_memory_allowed=True)
    assert contexts[0].run(pc.current) is None
    assert contexts[0].run(task_service.current) is None
    late = asyncio.create_task(execution_checkpoint.save("before_model"), context=contexts[0])
    with pytest.raises(TaskError, match="attempt_stale"):
        await late


async def test_detached_maintenance_has_no_task_lease_or_checkpoint_hook(execution_db):
    async def function(conversation, message, emit):
        async def background():
            assert pc.current() is None and task_service.current() is None and current_budget() is None
            await execution_checkpoint.save("before_model")
        await asyncio.create_task(background(), context=task_service.detached_context())
    await run(function)


async def test_recovery_tool_finds_saved_output_without_chat_history_and_rejects_other_tasks(execution_db, monkeypatch):
    from server.registry.task_tools import TaskProgressExecutor
    async def function(conversation, message, emit):
        async def body(sink):
            return "Saved output remains after prompt compaction."
        await host_run.execute(conversation, message, emit, body)
        raise Crash()
    with pytest.raises(Crash):
        await run(function)
    await task_service.recover_interrupted()
    async with execution_db() as db:
        other = Run(conversation_id="another-task", final_output="Private other-task output")
        db.add(other)
        await db.commit()
        foreign_id = other.id
    async with repository() as repo:
        row = await repo.get("live-task")
        version = row.version
    async def answer(conversation, message, emit, **kwargs):
        executor = TaskProgressExecutor()
        saved = await executor.execute({})
        assert saved["ok"] and saved["outputs"][0]["text"] == "Saved output remains after prompt compaction."
        assert saved["progress"]["continuation_ref"]["id"].startswith("run-output:")
        denied = await executor.execute({"run_id": foreign_id})
        assert denied["error_code"] == "task_run_scope_denied" and "Private" not in str(denied)
        assert not (await executor.execute({"task_id": "another-task"}))["ok"]
        with pc.for_worker("specialist"):
            assert (await executor.execute({}))["error_code"] == "task_context_unavailable"
        return "continued"
    monkeypatch.setattr(arslan, "_handle_answer", answer)
    assert await task_service.resume_turn("live-task", version, "live", lambda event: None) == "continued"
