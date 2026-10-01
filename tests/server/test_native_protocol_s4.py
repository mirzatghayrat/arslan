"""0.1.49 S4: OpenAI-compatible endpoints get the native tool protocol.

These tests read the real HTTP request bodies (httpx.MockTransport), not test
double arguments: what DeepSeek would actually receive.
"""
import json

import httpx
import pytest

from arslan.llm import trajectory as tj
from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers.openai_provider import OpenAIProvider
from server.orchestrator import tool_loop
from server.orchestrator.untrusted import DELIM_CLOSE, DELIM_OPEN

BASE = "https://api.deepseek.com"
THOUGHT = "  I should search first.\n\nThen answer.  "


def _reply(message, finish="stop"):
    return {"choices": [{"message": {"role": "assistant", **message}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def _call(cid, name, raw):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": raw}}


def _adapter(replies, bodies, model="deepseek-v4-flash"):
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=replies[min(len(bodies) - 1, len(replies) - 1)])
    adapter = LLMAdapter("openai", model, api_key="k", base_url=BASE)
    adapter._provider = OpenAIProvider(model=model, api_key="k", base_url=BASE,
                                       transport=httpx.MockTransport(handler))
    return adapter


class _Search:
    async def execute(self, args):
        return {"ok": True, "results": [{"title": f"hit for {args['query']}"}]}


async def _tools():
    return [{"key": "web_search", "description": "search the web"}]


async def _run(monkeypatch, replies, **kwargs):
    bodies = []
    adapter = _adapter(replies, bodies)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", _Search())
    result = await tool_loop.run_native(system="S", user_content="find x", history=[],
                                        emit=lambda e: None, on_chunk=lambda c: None,
                                        resolve_tools=_tools, **kwargs)
    return bodies, result


RAW = '{"query": "x" }'   # odd spacing: must be echoed verbatim, not re-serialized


@pytest.mark.asyncio
async def test_second_request_is_native_with_verbatim_reasoning_and_args(monkeypatch):
    monkeypatch.delenv("ARSLAN_TOOL_PROTOCOL", raising=False)
    bodies, result = await _run(monkeypatch, [
        _reply({"content": "", "reasoning_content": THOUGHT,
                "tool_calls": [_call("call_a", "web_search", RAW)]}, "tool_calls"),
        _reply({"content": "Answer.", "reasoning_content": "done"})])
    assert result["final"] == "Answer."
    msgs = bodies[1]["messages"]
    assistant = [m for m in msgs if m["role"] == "assistant"][0]
    assert assistant["reasoning_content"] == THOUGHT
    assert assistant["tool_calls"] == [{"id": "call_a", "type": "function",
                                        "function": {"name": "web_search", "arguments": RAW}}]
    tool = [m for m in msgs if m["role"] == "tool"]
    assert len(tool) == 1 and tool[0]["tool_call_id"] == "call_a"
    assert DELIM_OPEN in tool[0]["content"] and DELIM_CLOSE in tool[0]["content"]
    blob = json.dumps(bodies, ensure_ascii=False)
    assert "TOOL RESULT for" not in blob and "Native tool invocation completed" not in blob
    assert all(not k.startswith("_") for body in bodies for m in body["messages"] for k in m)
    assert msgs[-1]["role"] == "tool"   # no user turn pretending to be the tool result


@pytest.mark.asyncio
async def test_forced_step_keeps_the_same_tools_and_sets_tool_choice_none(monkeypatch):
    monkeypatch.delenv("ARSLAN_TOOL_PROTOCOL", raising=False)
    bodies, result = await _run(monkeypatch, [
        _reply({"content": "", "tool_calls": [_call("c1", "web_search", RAW)]}, "tool_calls"),
        _reply({"content": "Forced answer."})], max_tool_calls=1)
    assert result["final"] == "Forced answer."
    assert bodies[1]["tools"] == bodies[0]["tools"]
    assert bodies[1]["tool_choice"] == "none" and "tool_choice" not in bodies[0]


@pytest.mark.asyncio
async def test_legacy_switch_restores_the_old_wire_format(monkeypatch):
    monkeypatch.setenv("ARSLAN_TOOL_PROTOCOL", "legacy")
    bodies, _ = await _run(monkeypatch, [
        _reply({"content": "", "reasoning_content": THOUGHT,
                "tool_calls": [_call("c1", "web_search", RAW)]}, "tool_calls"),
        _reply({"content": "Answer."})])
    msgs = bodies[1]["messages"]
    assert not any(m["role"] == "tool" or "tool_calls" in m for m in msgs)
    assert "TOOL RESULT for web_search" in msgs[-1]["content"]
    assert THOUGHT not in json.dumps(bodies[1], ensure_ascii=False)


def test_continuation_is_only_echoed_to_the_endpoint_that_produced_it():
    flash = OpenAIProvider(model="deepseek-v4-flash", api_key="k", base_url=BASE)
    pro = OpenAIProvider(model="deepseek-v4-pro", api_key="k", base_url=BASE)
    msgs = [{"role": "user", "content": "t"},
            tj.assistant("", [{"id": "a", "name": "n", "arguments": {}, "arguments_raw": "{}"}],
                         continuation={"protocol": "openai", "endpoint": flash.endpoint_fingerprint(),
                                       "fields": {"reasoning_content": "r", "unexpected": 1}}),
            tj.tool_result("a", "n", "res")]
    on_flash = flash.build_trajectory_messages("S", msgs)
    assert on_flash[2]["reasoning_content"] == "r" and "unexpected" not in on_flash[2]
    assert "reasoning_content" not in pro.build_trajectory_messages("S", msgs)[2]


def test_host_run_presearch_is_user_context_not_a_fabricated_call():
    p = OpenAIProvider(model="deepseek-v4-flash", api_key="k", base_url=BASE)
    wire = p.build_trajectory_messages("S", [
        {"role": "user", "content": "t"},
        tj.tool_result(None, "web_search", "found", synthetic=True, legacy_call="{}")])
    assert [m["role"] for m in wire] == ["system", "user", "user"]
    assert "not requested by you" in wire[2]["content"] and "found" in wire[2]["content"]


@pytest.mark.asyncio
async def test_invalid_trajectory_degrades_to_legacy_for_the_rest_of_the_turn():
    calls = []

    class Native:
        def native_trajectory(self):
            return True

        async def chat_trajectory(self, *a, **k):
            calls.append("native")

        async def chat(self, system, user, history=None, tools=None):
            calls.append("legacy")
            return "ok"
    request = {"role": "user", "content": "t"}
    broken = [request, tj.assistant("", [{"id": "a", "name": "n", "arguments": {}, "arguments_raw": "{}"}])]
    state = {}
    assert await tool_loop._model_call(Native(), "S", broken, request, tools=None, schemas=[],
                                       forced=False, protocol=state) == "ok"
    assert state["legacy"] and "invalid trajectory" in state["reason"]
    await tool_loop._model_call(Native(), "S", [request], request, tools=None, schemas=[],
                                forced=False, protocol=state)
    assert calls == ["legacy", "legacy"]   # sticky: a valid history later stays legacy this turn
