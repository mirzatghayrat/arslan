"""0.1.49 S6: failure classes, retries, truncation recovery and breakers.

Fault injection at the HTTP layer (httpx.MockTransport) through the real
LLMAdapter/OpenAIProvider and run_native. Waiting is faked (model_call.sleep).
"""
import json

import httpx
import pytest

from arslan.execution_budget import Budget, Limits, scope
from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers.openai_provider import OpenAIProvider
from server.orchestrator import model_call, tool_loop

BASE = "https://api.deepseek.com"


def ok(message, finish="stop"):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", **message},
                                                  "finish_reason": finish}],
                                     "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})


def status(code, text="", headers=None):
    return httpx.Response(code, json={"error": {"message": text}}, headers=headers or {})


def call(cid, name, raw):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": raw}}


class Harness:
    def __init__(self, monkeypatch, responses):
        self.responses = list(responses)
        self.bodies = []
        self.slept = []

        async def fake_sleep(seconds):
            self.slept.append(seconds)
        monkeypatch.setattr(model_call, "sleep", fake_sleep)
        monkeypatch.setattr(model_call, "jitter", lambda: 0.0)

        def handler(request):
            self.bodies.append(json.loads(request.content))
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        self.adapter = LLMAdapter("openai", "deepseek-v4-flash", api_key="k", base_url=BASE)
        self.adapter._provider = OpenAIProvider(model="deepseek-v4-flash", api_key="k", base_url=BASE,
                                                transport=httpx.MockTransport(handler))
        monkeypatch.setattr(tool_loop, "_get_adapter", lambda: self.adapter)

    async def run(self, budget=None, **kwargs):
        async def tools():
            return [{"key": "web_search", "description": "search"}, {"key": "write_file", "description": "write"}]
        # A roomy budget unless a test is about the budget: the chat-turn default
        # (128k) is below the raise ceiling, which clamps the raised request.
        with scope(budget or Budget(Limits(tokens=10_000_000))):
            return await tool_loop.run_native(system="S", user_content="task", history=[], emit=lambda e: None,
                                              on_chunk=lambda c: None, resolve_tools=tools, **kwargs)


@pytest.fixture(autouse=True)
def _native(monkeypatch):
    monkeypatch.delenv("ARSLAN_TOOL_PROTOCOL", raising=False)


# ---------------------------------------------------------------- transport classes

async def test_429_honours_retry_after(monkeypatch):
    h = Harness(monkeypatch, [status(429, "rate limited", {"retry-after": "2"}), ok({"content": "fine"})])
    assert (await h.run())["final"] == "fine"
    assert h.slept == [2.0] and len(h.bodies) == 2


async def test_server_errors_back_off_then_succeed(monkeypatch):
    h = Harness(monkeypatch, [status(500), status(503), ok({"content": "fine"})])
    assert (await h.run())["final"] == "fine"
    assert h.slept == [1.0, 2.0]


async def test_persistent_503_fails_with_cause_attempts_and_no_further_model_calls(monkeypatch):
    h = Harness(monkeypatch, [status(503, "server overloaded")] * 5 + [ok({"content": "never"})])
    with pytest.raises(model_call.ModelCallError) as caught:
        await h.run()
    err = caught.value
    assert err.kind == "server" and err.status == 503 and err.attempts == 5
    assert "server overloaded" in str(err) and "5 attempts" in str(err)
    assert len(h.bodies) == 5        # nothing on the error path asked the model again
    assert h.slept == [1.0, 2.0, 4.0, 8.0]


@pytest.mark.parametrize("code,text,kind", [(402, "Insufficient Balance", "balance"),
                                            (401, "invalid api key", "auth"),
                                            (400, "unknown parameter foo", "input")])
async def test_non_retryable_failures_are_not_retried(monkeypatch, code, text, kind):
    h = Harness(monkeypatch, [status(code, text), ok({"content": "never"})])
    with pytest.raises(model_call.ModelCallError) as caught:
        await h.run()
    assert caught.value.kind == kind and len(h.bodies) == 1 and h.slept == []
    assert text in str(caught.value)


async def test_own_timeout_is_retried_once_and_reports_a_nonempty_cause(monkeypatch):
    calls = []

    class Slow:
        async def chat(self, *a, **k):
            calls.append(1)
            raise TimeoutError()
    monkeypatch.setattr(model_call, "sleep", lambda s: _noop())
    with pytest.raises(model_call.ModelCallError) as caught:
        await model_call.call_with_recovery(lambda: Slow().chat(), model_call.TurnRecovery())
    assert len(calls) == 2 and caught.value.kind == "stall"
    assert str(caught.value).strip() and "TimeoutError" in str(caught.value)


async def _noop():
    return None


async def test_turn_breaker_stops_retrying(monkeypatch):
    state = model_call.TurnRecovery(recoveries=["x"] * model_call.TURN_RECOVERY_LIMIT)
    h = Harness(monkeypatch, [status(500), ok({"content": "never"})])
    with pytest.raises(model_call.ModelCallError):
        await model_call.call_with_recovery(lambda: h.adapter.chat("S", "u"), state)
    assert len(h.bodies) == 1


async def test_waiting_never_outlives_the_work_budget(monkeypatch):
    h = Harness(monkeypatch, [status(429, "slow down", {"retry-after": "30"}), ok({"content": "never"})])
    with pytest.raises(model_call.ModelCallError):
        await model_call.call_with_recovery(lambda: h.adapter.chat("S", "u"), model_call.TurnRecovery(),
                                            remaining_s=lambda: 10.0)
    assert h.slept == []


# ---------------------------------------------------------------- protocol and context

async def test_protocol_400_degrades_to_legacy_once_and_sticks(monkeypatch):
    h = Harness(monkeypatch, [
        ok({"content": "", "tool_calls": [call("c1", "web_search", '{"query": "q"}')]}, "tool_calls"),
        status(400, "Missing reasoning_content in assistant message"),
        ok({"content": "", "tool_calls": [call("c2", "web_search", '{"query": "r"}')]}, "tool_calls"),
        ok({"content": "done"})])

    class Search:
        async def execute(self, args):
            return {"ok": True, "results": [args["query"]]}
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", Search())
    assert (await h.run())["final"] == "done"
    assert any(m["role"] == "tool" for m in h.bodies[1]["messages"])            # native attempt
    assert not any(m["role"] == "tool" for m in h.bodies[2]["messages"])        # legacy re-send
    assert not any(m["role"] == "tool" for m in h.bodies[3]["messages"])        # stays legacy
    assert "TOOL RESULT for web_search" in h.bodies[3]["messages"][-1]["content"]


async def test_context_overflow_compacts_once_then_gives_up(monkeypatch):
    h = Harness(monkeypatch, [status(400, "maximum context length exceeded"),
                              status(400, "maximum context length exceeded"), ok({"content": "never"})])
    with pytest.raises(model_call.ModelCallError) as caught:
        await h.run()
    assert caught.value.kind == "context" and len(h.bodies) == 2
    assert "compacted context" in str(caught.value)


# ---------------------------------------------------------------- truncation

async def test_cut_answer_is_raised_then_continued(monkeypatch):
    h = Harness(monkeypatch, [ok({"content": "Hel"}, "length"), ok({"content": "Hello wor"}, "length"),
                              ok({"content": "ld."})])
    assert (await h.run())["final"] == "Hello world."
    assert [b["max_tokens"] for b in h.bodies] == [32_768, 131_072, 131_072]
    tail = h.bodies[2]["messages"][-2:]
    assert tail[0] == {"role": "assistant", "content": "Hello wor"}
    assert tail[1]["role"] == "user" and "cut off" in tail[1]["content"]


async def test_cut_tool_arguments_are_never_executed(monkeypatch):
    raw = '{"path": "report.md", "content": "Quarterly results were'
    h = Harness(monkeypatch, [ok({"content": "", "tool_calls": [call("c1", "write_file", raw)]}, "length"),
                              ok({"content": "", "tool_calls": [call("c1", "write_file", raw)]}, "length"),
                              ok({"content": "I will write it in parts."})])
    executed = []

    class Write:
        async def execute(self, args):
            executed.append(args)
            return {"ok": True}
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "write_file", Write())
    result = await h.run()
    assert executed == []
    assert result["tool_trace"][0]["result"]["code"] == "output_truncated"
    tool_msgs = [m for m in h.bodies[2]["messages"] if m["role"] == "tool"]
    assert tool_msgs and "nothing was executed" in tool_msgs[0]["content"]


async def test_reasoning_only_cut_is_raised(monkeypatch):
    h = Harness(monkeypatch, [ok({"content": "", "reasoning_content": "long thought"}, "length"),
                              ok({"content": "answer"})])
    assert (await h.run())["final"] == "answer"
    assert h.bodies[1]["max_tokens"] == 131_072


async def test_budget_clamped_cut_is_not_raised(monkeypatch):
    h = Harness(monkeypatch, [ok({"content": "partial"}, "length"), ok({"content": "never"})])
    result = await h.run(budget=Budget(Limits(tokens=1_000)))
    assert len(h.bodies) == 1 and h.bodies[0]["max_tokens"] == 1_000
    assert result["final"] == "partial"


async def test_repeated_cut_calls_trip_the_breaker_and_force_an_answer(monkeypatch):
    raw = '{"path": "a.md", "content": "x'
    cut = ok({"content": "", "tool_calls": [call("c", "write_file", raw)]}, "length")
    # step1 cut+raise, step2 cut+raise, step3 cut (raise cap reached), step4 forced
    h = Harness(monkeypatch, [cut] * 5 + [ok({"content": "Could not write it; summary instead."})])
    from server.registry import executors

    class Write:
        async def execute(self, args):
            raise AssertionError("must not run")
    monkeypatch.setitem(executors.EXECUTORS, "write_file", Write())
    result = await h.run()
    assert result["final"] == "Could not write it; summary instead."
    assert h.bodies[-1]["tool_choice"] == "none"


# ---------------------------------------------------------------- user-facing error

async def test_error_frame_is_never_empty_and_mentions_retries():
    from server.orchestrator import llm_errors
    frame = await llm_errors.error_frame(TimeoutError())
    assert frame["message"].strip()
    raw = model_call.ModelCallError("server", status=503, excerpt="Service Unavailable", attempts=5,
                                    waited_s=15, recoveries=["retried after server 503"])
    frame = await llm_errors.error_frame(raw)          # unrecognised category: exact text
    assert "Service Unavailable" in frame["message"] and "5 attempts over 15s" in frame["message"]
    rate = model_call.ModelCallError("rate", status=429, excerpt="429 Too Many Requests", attempts=5,
                                     waited_s=15, recoveries=[])
    frame = await llm_errors.error_frame(rate)         # translated category keeps the retry facts
    assert all("5" in text and "15" in text for text in frame["message_i18n"].values())


async def test_cut_answer_is_continued_on_the_legacy_path_too(monkeypatch):
    monkeypatch.setenv("ARSLAN_TOOL_PROTOCOL", "legacy")
    h = Harness(monkeypatch, [ok({"content": "Hel"}, "length"), ok({"content": "Hello wor"}, "length"),
                              ok({"content": "ld."})])
    assert (await h.run())["final"] == "Hello world."
    tail = h.bodies[2]["messages"][-2:]
    assert tail[0] == {"role": "assistant", "content": "Hello wor"} and "cut off" in tail[1]["content"]


async def test_context_recovery_is_reported_as_compaction(monkeypatch):
    h = Harness(monkeypatch, [status(400, "maximum context length exceeded"), ok({"content": "fits now"})])
    result = await h.run()
    assert result["final"] == "fits now" and result["history_compacted"] is True


async def test_reasoning_rides_only_on_a_single_replys_own_text(monkeypatch):
    h = Harness(monkeypatch, [ok({"content": "H", "reasoning_content": "A"}, "length"),
                              ok({"content": "Hello ", "reasoning_content": "B"}, "length"),
                              ok({"content": "wor", "reasoning_content": "C"}, "length"),
                              ok({"content": "ld"})])
    assert (await h.run())["final"] == "Hello world"
    first, second = h.bodies[2]["messages"][-2], h.bodies[3]["messages"][-2]
    assert first == {"role": "assistant", "content": "Hello ", "reasoning_content": "B"}
    assert second == {"role": "assistant", "content": "Hello wor"}   # joined text: no one reply's reasoning
