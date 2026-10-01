"""0.1.49 S7: streamed replies are assembled exactly; stalls are detected on
real deltas only; interrupted streams are never taken as answers."""
import asyncio
import json

import httpx
import pytest

from arslan.llm import stream_assembly
from arslan.llm.providers.openai_provider import OpenAIProvider
from server.orchestrator import model_call

BASE = "https://api.deepseek.com"


def sse(*frames, done=True, keepalive_every=0):
    out = []
    for i, frame in enumerate(frames):
        if keepalive_every and i % keepalive_every == 0:
            out.append(": keep-alive\n\n")
        out.append("data: " + json.dumps(frame) + "\n\n")
    if done:
        out.append("data: [DONE]\n\n")
    return "".join(out).encode()


def delta(**d):
    return {"choices": [{"index": 0, "delta": d, "finish_reason": None}]}


def finish(reason, usage=None):
    frame = {"choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}
    if usage:
        frame["usage"] = usage
    return frame


def provider(handler, base=BASE):
    return OpenAIProvider(model="deepseek-v4-flash", api_key="k", base_url=base,
                          transport=httpx.MockTransport(handler))


def stream_response(body):
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


ARGS = '{"path": "report.md", "content": "line one\\nline two"}'


async def test_interleaved_tool_call_deltas_assemble_exactly():
    pieces = [ARGS[i:i + 7] for i in range(0, len(ARGS), 7)]
    # index 1 is announced before index 0; later frames resend an empty id
    frames = [delta(role="assistant", reasoning_content="Think "), delta(reasoning_content="hard."),
              delta(tool_calls=[{"index": 1, "id": "call_b", "type": "function",
                                 "function": {"name": "read_file", "arguments": '{"path": "x"}'}}]),
              delta(tool_calls=[{"index": 0, "id": "call_a", "type": "function",
                                 "function": {"name": "write_file", "arguments": ""}}])]
    frames += [delta(tool_calls=[{"index": 0, "id": "", "function": {"arguments": p}}]) for p in pieces]
    frames += [finish("tool_calls", {"prompt_tokens": 9, "completion_tokens": 3, "total_tokens": 12})]
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return stream_response(sse(*frames, keepalive_every=2))
    resp = await provider(handler).chat([{"role": "user", "content": "t"}], tools=[{"type": "function",
        "function": {"name": "write_file", "parameters": {}}}], stream=True)
    assert bodies[0]["stream"] is True and bodies[0]["stream_options"] == {"include_usage": True}
    assert [c["id"] for c in resp.tool_calls] == ["call_a", "call_b"]
    assert resp.tool_calls[0]["arguments_raw"] == ARGS
    assert resp.tool_calls[0]["function"]["arguments"]["content"] == "line one\nline two"
    assert resp.continuation["fields"] == {"reasoning_content": "Think hard."}
    assert resp.finish_reason == "tool_calls" and resp.usage["total_tokens"] == 12


async def test_reasoning_and_content_interleave_and_keepalives_are_ignored():
    frames = [delta(reasoning_content="a"), delta(content="Hel"), delta(reasoning_content="b"),
              delta(content="lo"), finish("stop")]
    resp = await provider(lambda r: stream_response(sse(*frames, keepalive_every=1))).chat(
        [{"role": "user", "content": "t"}], stream=True)
    assert resp.content == "Hello" and resp.continuation["fields"]["reasoning_content"] == "ab"


async def test_a_plain_json_answer_to_a_stream_request_is_still_parsed():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "json"},
                                                      "finish_reason": "stop"}], "usage": {}})
    resp = await provider(handler).chat([{"role": "user", "content": "t"}], stream=True)
    assert resp.content == "json"


async def test_stream_that_ends_mid_reply_is_an_error_not_an_answer():
    body = sse(delta(content="half an ans"), done=False)
    with pytest.raises(httpx.RemoteProtocolError):
        await provider(lambda r: stream_response(body)).chat([{"role": "user", "content": "t"}], stream=True)


async def test_http_error_in_stream_mode_carries_the_providers_words():
    def handler(request):   # a real streamed body: unread until the provider reads it
        return httpx.Response(402, headers={"content-type": "application/json"},
                              stream=_Trickle([(0.0, b'{"error": {"message": "Insufficient Balance"}}')]))
    with pytest.raises(httpx.HTTPStatusError) as caught:
        await provider(handler).chat([{"role": "user", "content": "t"}], stream=True)
    assert "Insufficient Balance" in str(caught.value)


class _Trickle(httpx.AsyncByteStream):
    """Emit chunks with real delays (for the watchdog)."""

    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for delay, chunk in self.chunks:
            await asyncio.sleep(delay)
            yield chunk


def trickle(chunks):
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=_Trickle(chunks))


async def test_keepalives_alone_are_a_stall(monkeypatch):
    monkeypatch.setattr(stream_assembly, "IDLE_S", 0.3)
    chunks = [(0.1, b": keep-alive\n\n")] * 8
    with pytest.raises(stream_assembly.StreamStalled):
        await provider(lambda r: trickle(chunks)).chat([{"role": "user", "content": "t"}], stream=True)


async def test_steady_real_deltas_are_not_a_stall(monkeypatch):
    monkeypatch.setattr(stream_assembly, "IDLE_S", 0.3)
    chunks = [(0.1, ("data: " + json.dumps(delta(reasoning_content="x")) + "\n\n").encode())] * 8
    chunks += [(0.0, ("data: " + json.dumps(finish("stop")) + "\n\ndata: [DONE]\n\n").encode())]
    resp = await provider(lambda r: trickle(chunks)).chat([{"role": "user", "content": "t"}], stream=True)
    assert resp.finish_reason == "stop" and resp.continuation["fields"]["reasoning_content"] == "x" * 8


async def test_a_stall_is_retried_once_then_reported(monkeypatch):
    monkeypatch.setattr(stream_assembly, "IDLE_S", 0.2)

    async def no_wait(seconds):
        return None
    monkeypatch.setattr(model_call, "sleep", no_wait)
    requests = []

    def handler(request):
        requests.append(1)
        return trickle([(0.1, b": keep-alive\n\n")] * 6)
    p = provider(handler)
    with pytest.raises(model_call.ModelCallError) as caught:
        await model_call.call_with_recovery(
            lambda: p.chat([{"role": "user", "content": "t"}], stream=True), model_call.TurnRecovery())
    assert len(requests) == 2 and caught.value.kind == "stall"
    assert "stalled" in str(caught.value)


def test_only_known_endpoints_stream_tool_calls():
    assert OpenAIProvider(model="m", base_url=BASE).streams_tool_calls()
    assert OpenAIProvider(model="m", base_url="https://openrouter.ai/api/v1").streams_tool_calls()
    assert not OpenAIProvider(model="m", base_url="http://127.0.0.1:11434/v1").streams_tool_calls()


async def test_native_turn_streams_on_deepseek_and_echoes_streamed_reasoning(monkeypatch):
    from arslan.llm.adapter import LLMAdapter
    from server.orchestrator import tool_loop
    monkeypatch.delenv("ARSLAN_TOOL_PROTOCOL", raising=False)
    replies = [sse(delta(reasoning_content="search first"),
                   delta(tool_calls=[{"index": 0, "id": "c1", "type": "function",
                                      "function": {"name": "web_search", "arguments": '{"query": "q"}'}}]),
                   finish("tool_calls")),
               sse(delta(content="Answer."), finish("stop"))]
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return stream_response(replies[len(bodies) - 1])
    adapter = LLMAdapter("openai", "deepseek-v4-flash", api_key="k", base_url=BASE)
    adapter._provider = provider(handler)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    class Search:
        async def execute(self, args):
            return {"ok": True, "results": ["hit"]}
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", Search())

    async def tools():
        return [{"key": "web_search", "description": "search"}]
    result = await tool_loop.run_native(system="S", user_content="t", history=[], emit=lambda e: None,
                                        on_chunk=lambda c: None, resolve_tools=tools)
    assert result["final"] == "Answer." and all(b["stream"] for b in bodies)
    assistant = [m for m in bodies[1]["messages"] if m["role"] == "assistant"][0]
    assert assistant["reasoning_content"] == "search first"
