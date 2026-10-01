"""0.1.49 S3: run_native keeps a neutral trajectory that is valid at every step.

The golden test proves the rendered payloads did not change; these tests prove
what the new representation guarantees on its own: every model call's results
are bound to its ids, continuation state is kept on the assistant message, and
compaction never splits a call from its results.
"""
import pytest

from arslan.llm import trajectory as tj
from arslan.runtime_policy import bounded_history
from server.orchestrator import tool_loop
from tests.server import test_trajectory_golden as golden


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(golden.SCENARIOS))
async def test_trajectory_is_valid_at_every_model_request(monkeypatch, name):
    seen = []
    real = tool_loop._render_request

    def spy(convo, current_request):
        snapshot = [dict(m) for m in convo]
        tj.validate(snapshot)
        seen.append(snapshot)
        return real(convo, current_request)
    monkeypatch.setattr(tool_loop, "_render_request", spy)
    await golden._run(name, monkeypatch)
    assert seen
    ids = [c["id"] for m in seen[-1] if m.get("role") == "assistant" for c in m.get("tool_calls") or []]
    assert len(ids) == len(set(ids)), "tool call ids must be unique within the turn"
    for snapshot in seen:
        for message in snapshot:
            if message.get("role") == "tool":
                assert "_legacy_call" not in message, "a model call's result was left unclaimed"
                assert message["tool_call_id"]


@pytest.mark.asyncio
async def test_presearch_stays_host_run_and_model_calls_are_bound(monkeypatch):
    seen = []
    real = tool_loop._render_request

    def spy(convo, current_request):
        seen.append([dict(m) for m in convo])
        return real(convo, current_request)
    monkeypatch.setattr(tool_loop, "_render_request", spy)
    await golden._presearch(monkeypatch)
    first, second = seen
    assert [m.get("_synthetic") for m in first if m["role"] == "tool"] == [True]
    model_group = [m for m in second if m.get("role") in ("assistant", "tool")]
    assert model_group[-2]["tool_calls"][0]["id"] == model_group[-1]["tool_call_id"]
    assert not model_group[-1].get("_synthetic")


@pytest.mark.asyncio
async def test_continuation_and_finish_are_kept_on_the_assistant_message(monkeypatch):
    seen = []
    real = tool_loop._render_request

    def spy(convo, current_request):
        seen.append([dict(m) for m in convo])
        return real(convo, current_request)
    monkeypatch.setattr(tool_loop, "_render_request", spy)
    cont = {"protocol": "openai", "endpoint": "fp", "fields": {"reasoning_content": "  why\n"}}
    reply = golden._Resp(None, [golden._tc("web_search", {"query": "q"}, ""), golden._tc("web_search", {"query": "r"}, "")])
    reply.continuation, reply.finish_reason = cont, "tool_calls"
    adapter = golden._Recorder([reply, golden._Resp("done")])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", golden._Search())
    await tool_loop.run_native(system="S", user_content="t", history=[], emit=lambda e: None,
                               on_chunk=lambda c: None, resolve_tools=golden._resolve)
    assistant = [m for m in seen[-1] if m["role"] == "assistant"][0]
    assert assistant["_continuation"] == cont and assistant["_finish"] == "tool_calls"
    # empty provider ids were repaired to unique per-turn ids and bound to results
    ids = [c["id"] for c in assistant["tool_calls"]]
    assert len(set(ids)) == 2 and all(ids)
    assert [m["tool_call_id"] for m in seen[-1] if m["role"] == "tool"] == ids


def test_claim_binds_only_single_records():
    convo = [{"role": "user", "content": "t"}, tj.assistant(None, [])]
    marks = [(len(convo), "a")]
    convo.append(tj.tool_result(None, "x", "r", synthetic=True, legacy_call="{}"))
    marks.append((len(convo), "b"))           # call b appended nothing (escaped stub)
    marks.append((len(convo), "c"))
    convo.append(tj.tool_result(None, "y", "r1", synthetic=True, legacy_call="{}"))
    convo.append(tj.tool_result(None, "y", "r2", synthetic=True, legacy_call="{}"))  # two records
    tool_loop._claim_results(convo, marks)
    assert convo[2]["tool_call_id"] == "a" and "_synthetic" not in convo[2]
    assert convo[3].get("_synthetic") and convo[4].get("_synthetic")


def _group(n, body):
    calls = [{"id": f"c{i}", "name": "web_extract", "arguments": {}, "arguments_raw": "{}"} for i in range(n)]
    return [tj.assistant(None, calls)] + [tj.tool_result(f"c{i}", "web_extract", f"{body}{i}") for i in range(n)]


def test_oversized_unprotected_group_sheds_oldest_bodies_and_keeps_pairing():
    import json
    group = _group(3, "x" * 2000)
    limit = len(json.dumps(group, ensure_ascii=False)) - 1000   # one body too many
    kept, compacted = bounded_history([{"role": "user", "content": "task"}] + group, max_chars=limit)
    tj.validate(kept)
    tools = [m for m in kept if m["role"] == "tool"]
    assert len(tools) == 3 and compacted
    assert [t["content"] == tj.OMITTED_RESULT for t in tools] == [True, False, False]
    assert len(json.dumps(kept, ensure_ascii=False)) <= limit


def test_protected_tail_is_delivered_whole():
    history = [{"role": "user", "content": "task"}] + _group(3, "x" * 400)
    kept, _ = bounded_history(history, max_chars=1000, preserve_tail=4)
    assert all(m["content"] != tj.OMITTED_RESULT for m in kept if m["role"] == "tool")


def test_eviction_takes_whole_groups():
    history = [{"role": "user", "content": "task"}] + _group(2, "o" * 300) + _group(1, "n" * 300)
    kept, compacted = bounded_history(history, max_chars=800)
    tj.validate(kept)
    assert compacted and [m["role"] for m in kept] == ["assistant", "tool"]
    assert kept[1]["content"].startswith("n")


async def _repair_assistant(monkeypatch, replies):
    """Run one validation-repair cycle; return the repair-step assistant message."""
    from arslan.models import LLMResponse
    from tests.server.test_task_validation import check, run_contract
    queue = [LLMResponse(usage={}, **r) for r in replies]
    seen = []
    real = tool_loop._render_request

    def spy(convo, current_request):
        seen.append([dict(m) for m in convo])
        return real(convo, current_request)
    monkeypatch.setattr(tool_loop, "_render_request", spy)

    class Adapter:
        async def chat(self, *args, **kwargs):
            return queue.pop(0)
    monkeypatch.setattr(tool_loop, "_get_adapter", Adapter)

    async def tools():
        return []

    async def body(emit):
        return await tool_loop.run_native(system="Check", user_content="fixture", history=[], resolve_tools=tools,
                                          emit=emit, on_chunk=lambda text: None, allow_escalation=False)
    await run_contract([check(equals="right")], body)
    return [m for m in seen[-1] if m["role"] == "assistant"][-1]


CONT = {"protocol": "openai", "endpoint": "fp", "fields": {"reasoning_content": "r1"}}


async def test_validation_repair_keeps_the_replys_own_continuation(execution_db, monkeypatch):
    message = await _repair_assistant(monkeypatch, [
        {"content": "wrong", "continuation": CONT}, {"content": "right"}])
    assert message["content"] == "wrong" and message["_continuation"] == CONT


async def test_validation_repair_never_pairs_a_salvaged_answer_with_foreign_reasoning(execution_db, monkeypatch):
    message = await _repair_assistant(monkeypatch, [
        {"content": "", "continuation": CONT},   # empty reply -> salvage request answers instead
        {"content": "salvaged"}, {"content": "right"}])
    assert message["content"] == "salvaged" and message["_continuation"] is None
