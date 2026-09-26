import hashlib

import pytest

from arslan.companion.content_policy import normalized_memory
from server.orchestrator import memory
from server.orchestrator.tool_caller import ToolCaller, set_caller, reset_caller
from server.registry.memory_executors import RecallExecutor, RememberExecutor
from server.services import personal_context as pc
from server.services.memory_activation import activate_sync
from server.services.memory_migration import migrate_legacy_sync


@pytest.fixture
async def active_memory(execution_db):
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
        await db.run_sync(activate_sync)


async def execute(args, *, actor="host", spawn_id=None, context=None, recall=False):
    token = set_caller(ToolCaller(actor=actor, spawn_id=spawn_id, conversation_id="conversation-a"))
    try:
        with pc.bind(context or pc.TaskMemoryContext(task_id="task-a", run_id="run-a", model_is_local=True)):
            return await (RecallExecutor() if recall else RememberExecutor()).execute(args)
    finally:
        reset_caller(token)


async def test_host_inference_is_proposed_and_not_recalled(active_memory):
    result = await execute({"kind": "fact", "action": "append", "content": "Use concise answers",
                            "origin": "user", "confirmed": True})
    assert result["ok"] and result["requires_confirmation"] and not result["saved"]
    assert (await execute({"kind": "fact"}, recall=True))["hits"] == []


async def test_explicit_save_is_bound_to_exact_user_content(active_memory):
    content = "Use examples"
    ctx = pc.TaskMemoryContext(task_id="task-a", run_id="run-a", model_is_local=True,
        explicit_save_ref="message:1", allow_global_save=True,
        explicit_save_digest=hashlib.sha256(normalized_memory(content).encode()).hexdigest())
    altered = await execute({"kind": "fact", "action": "append", "content": "Use lengthy answers"}, context=ctx)
    assert altered["status"] == "proposed"
    result = await execute({"kind": "fact", "action": "append", "content": content}, context=ctx)
    assert result["saved"] and result["status"] == "active"


async def test_worker_cannot_reuse_host_confirmation(active_memory):
    content = "Use examples"
    ctx = pc.TaskMemoryContext(task_id="task-a", run_id="run-a", explicit_save_ref="message:1",
        allow_global_save=True, explicit_save_digest=hashlib.sha256(normalized_memory(content).encode()).hexdigest())
    result = await execute({"kind": "preference", "action": "append", "content": content},
                           actor="spawn", spawn_id=3, context=ctx)
    assert result["status"] == "proposed" and result["scope"] == {"kind": "expert", "id": "3"}


@pytest.mark.parametrize("action", ["delete", "mark_stale"])
async def test_destructive_memory_tools_require_user_review(active_memory, action):
    result = await execute({"kind": "fact", "action": action, "target_id": 1})
    assert not result["ok"] and result["code"] == "user_confirmation_required"


async def test_tool_read_cannot_bypass_cloud_gate(active_memory):
    await memory.add_manual_fact("Private local preference")
    ctx = pc.TaskMemoryContext(task_id="task-a", run_id="run-a")
    assert (await execute({"kind": "fact"}, context=ctx, recall=True))["hits"] == []


async def test_supersede_is_a_versioned_proposal(active_memory):
    fact = await memory.add_manual_fact("Use short replies")
    args = {"kind": "fact", "action": "supersede", "target_id": fact.id, "content": "Use long replies"}
    assert (await execute(args))["code"] == "memory_version_required"
    result = await execute({**args, "expected_version": 1})
    assert result["status"] == "proposed" and result["requires_confirmation"]
    assert (await memory.list_facts())[0].content == "Use short replies"
