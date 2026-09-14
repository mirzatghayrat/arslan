import asyncio

import httpx
import pytest

from arslan.execution_budget import Budget, BudgetExceeded, Limits, current, scope
from arslan.models import LLMResponse
from arslan.runtime_policy import FailureKind, ProgressPolicy, bounded_history, exception_kind, tool_failure
from server.orchestrator import tool_loop
from server.services.task_repository import TaskError


def call(index, name="fixture_read"):
    return {"id": str(index), "type": "function",
            "function": {"name": name, "arguments": {"index": index}}}


async def tools():
    return [{"key": "fixture_read", "description": "Read one synthetic fixture"}]


async def test_more_than_eight_rounds_finish_within_one_shared_budget(monkeypatch):
    seen = []
    class Adapter:
        async def chat(self, system, user, **kwargs):
            current().model_request(100)
            index = current().model_requests
            assert kwargs["tools"] is not None
            return LLMResponse(usage={}, content="Verified eleven inputs." if index == 12 else "",
                               tool_calls=[] if index == 12 else [call(index)])
    class Executor:
        async def execute(self, arguments):
            seen.append((current().id, arguments["index"]))
            return {"ok": True, "external": False, "summary": str(arguments["index"])}
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: Adapter())
    monkeypatch.setitem(tool_loop.EXECUTORS, "fixture_read", Executor())
    with scope(Budget(Limits(model_requests=16, tool_calls=15))) as budget:
        result = await tool_loop.run_native(system="s", user_content="Read eleven inputs", history=[],
            resolve_tools=tools, emit=lambda event: None, on_chunk=lambda text: None)
        assert budget.model_requests == 12 and budget.tool_calls == 11
        assert all(identity == budget.id for identity, _ in seen)
    assert result["final"] == "Verified eleven inputs."
    assert result["stop_reason"] is None


async def test_repeated_identical_work_stops_without_language_markers(monkeypatch):
    calls = []
    class Adapter:
        async def chat(self, system, user, **kwargs):
            current().model_request(100)
            if kwargs["tools"] is None:
                assert "no progress" in system
                return LLMResponse(usage={}, content="One source verified; remaining coverage is blocked.")
            return LLMResponse(usage={}, content="", tool_calls=[call(1)])
    class Executor:
        async def execute(self, arguments):
            calls.append(arguments)
            return {"ok": True, "external": False, "summary": "same evidence"}
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: Adapter())
    monkeypatch.setitem(tool_loop.EXECUTORS, "fixture_read", Executor())
    result = await tool_loop.run_native(system="s", user_content="Read evidence", history=[],
        resolve_tools=tools, emit=lambda event: None, on_chunk=lambda text: None)
    assert len(calls) == 5
    assert result["stop_reason"] == "task_no_progress"
    assert "blocked" in result["final"]


async def test_multiple_calls_cannot_exceed_shared_tool_budget_and_are_serial(monkeypatch):
    executed, in_flight = [], 0
    class Adapter:
        async def chat(self, *args, **kwargs):
            current().model_request(100)
            return LLMResponse(usage={}, content="", tool_calls=[call(i) for i in range(4)])
    class Executor:
        async def execute(self, arguments):
            nonlocal in_flight
            in_flight += 1
            assert in_flight == 1
            await asyncio.sleep(0)
            executed.append(arguments["index"])
            in_flight -= 1
            return {"ok": True, "external": False, "summary": str(arguments["index"])}
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: Adapter())
    monkeypatch.setitem(tool_loop.EXECUTORS, "fixture_read", Executor())
    with scope(Budget(Limits(tool_calls=2))) as budget:
        with pytest.raises(BudgetExceeded, match="tool_calls"):
            await tool_loop.run_native(system="s", user_content="Read", history=[],
                resolve_tools=tools, emit=lambda event: None, on_chunk=lambda text: None)
        assert budget.tool_calls == 2
    assert executed == [0, 1]


@pytest.mark.parametrize("error,retries", [(TimeoutError(), 2), (ValueError("bad input"), 1),
    (PermissionError("denied"), 1), (TaskError("task_attempt_stale"), 1)])
async def test_only_transient_model_errors_retry(monkeypatch, error, retries):
    seen = []
    class Adapter:
        async def chat(self, *args, **kwargs):
            seen.append(True)
            raise error
    with pytest.raises(type(error)):
        await tool_loop._chat_retry(Adapter(), "s", "u")
    assert len(seen) == retries


@pytest.mark.parametrize("error", [BudgetExceeded("model_requests"), TaskError("task_attempt_stale")])
@pytest.mark.parametrize("salvage", ["plain", "findings"])
async def test_answer_salvage_never_swallows_runtime_control(monkeypatch, error, salvage):
    async def unavailable():
        return None
    monkeypatch.setattr("server.services.llm_factory.build_synthesis_adapter", unavailable)
    class Adapter:
        async def chat(self, *args, **kwargs):
            raise error
    with pytest.raises(type(error)):
        if salvage == "plain":
            await tool_loop._salvage_plain(Adapter(), "s", "u")
        else:
            await tool_loop._synthesize_from_findings(Adapter(), "s", "u", [
                {"tool": "read", "result": {"ok": True, "text": "synthetic evidence"}}])


def test_failure_kinds_are_diagnostic_not_permission_grants():
    assert exception_kind(httpx.ConnectError("offline")) == FailureKind.RETRYABLE
    response = httpx.Response(429, request=httpx.Request("GET", "https://fixture.invalid"))
    assert exception_kind(httpx.HTTPStatusError("rate limited", request=response.request, response=response)) == FailureKind.RETRYABLE
    assert tool_failure({"ok": False, "code": "task_reconciliation_required"}) == FailureKind.UNCERTAIN
    assert tool_failure({"ok": False, "failure_kind": {"untrusted": "retryable"}}) == FailureKind.PERMANENT
    assert tool_failure({"ok": True}) is None


def test_progress_hashes_survive_reconstruction_without_storing_inputs():
    first = ProgressPolicy()
    assert first.observe("read", {"path": "fixture"}, {"ok": True, "text": "evidence"})
    second = ProgressPolicy(seen=set(first.seen))
    assert not second.observe("read", {"path": "fixture"}, {"ok": True, "text": "evidence"})
    assert second.stalled == 1
    assert all(len(value) == 64 and "fixture" not in value for value in second.seen)


def test_compaction_preserves_opaque_provider_and_response_pair():
    opaque = {"role": "assistant", "content": [{"type": "provider_content", "provider": "gemini",
              "parts": [{"functionCall": {"name": "read"}, "thoughtSignature": "opaque-fixture"}]}]}
    response = {"role": "user", "content": [{"type": "function_response", "name": "read", "response": {"result": "ok"}}]}
    kept, compacted = bounded_history([{"role": "user", "content": "x" * 1000}, opaque, response], max_chars=10)
    assert compacted and kept == [opaque, response]
    assert kept[0] is opaque and kept[1] is response
