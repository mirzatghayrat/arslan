"""A specialist's recall never returns sensitive memory, whatever the host's turn allows (C2a follow-up).

The v1 RecallExecutor tests of this went with memory v1 (C2a-1). On v2, recall runs through
memory_tools_v2.recall with the caller's context.
"""
from server.orchestrator import memory
from server.orchestrator.tool_caller import ToolCaller, reset_caller, set_caller
from server.registry.memory_executors import RecallExecutor
from server.services import personal_context as pc


async def _recall(actor, spawn_id=None):
    host_turn = pc.TaskMemoryContext(task_id="t", run_id="r", model_is_local=True, allow_sensitive=True,
                                     query="dog")
    token = set_caller(ToolCaller(actor=actor, spawn_id=spawn_id, conversation_id="c"))
    try:
        with pc.bind(host_turn):
            result = await RecallExecutor().execute({"kind": "fact", "query": "dog"})
    finally:
        reset_caller(token)
    return " ".join(hit["content"] for hit in result["hits"])


async def test_the_host_sees_a_sensitive_fact_its_turn_allows(execution_db):
    await memory.add_manual_fact("user's dog is named Rex")
    await memory.add_manual_fact("user's dog takes heart medicine", sensitive=True)
    seen = await _recall("host")
    assert "Rex" in seen and "heart medicine" in seen


async def test_a_specialist_never_sees_a_sensitive_fact(execution_db):
    await memory.add_manual_fact("user's dog is named Rex")
    await memory.add_manual_fact("user's dog takes heart medicine", sensitive=True)
    seen = await _recall("spawn", spawn_id=5)
    assert "Rex" in seen
    assert "heart medicine" not in seen


def test_a_specialist_callers_context_is_the_worker_narrowing():
    # ③Hands' review: one narrowing for every specialist path, so they cannot drift apart again.
    from server.services.memory_tools_v2 import _context
    host = pc.TaskMemoryContext(task_id="t", run_id="r", allow_sensitive=True, allow_global_save=True,
                                explicit_save_ref="ref", explicit_save_digest="digest")
    token = set_caller(ToolCaller(actor="spawn", spawn_id=5, conversation_id="c"))
    try:
        with pc.bind(host):
            narrowed = _context(ToolCaller(actor="spawn", spawn_id=5, conversation_id="c"))
            with pc.for_worker("5") as worker:
                assert narrowed == worker == pc.worker_context(host, "5")
    finally:
        reset_caller(token)
    assert narrowed.allow_sensitive is False and narrowed.allow_global_save is False
    assert narrowed.explicit_save_ref is None and narrowed.explicit_save_digest is None
    assert narrowed.expert_id == "5"
