"""K8b: Claude's answer goes out while it is written (card K8; ⓪Plan's answers in the K8b plan).

Driven through the real LLMAdapter and AnthropicProvider on a Messages-SSE mock, so the text reaches K8a's
loop (window, corrections, invariant) exactly as in production:
- Claude on Anthropic's host streams; another Anthropic-protocol endpoint answers whole (Q1, the same test
  as context editing);
- the thinking a step returned is replayed byte for byte in the next request of the turn (K1);
- once text went out, a retryable error in the stream is not resent: the turn ends interrupted (Q3);
- a reply with a delta this version does not know never runs its tool call (Q5);
- a stream that only pings is still cut by the turn's time (Q2).
"""
import asyncio
import json

import httpx
import pytest

from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers.anthropic_provider import AnthropicProvider
from server.orchestrator import model_call, tool_loop
from server.services import host_run, runtime_messages
from tests.llm.test_k8b_anthropic_stream import block, end, event, piece, sse, start, stop, whole

BASE = "https://api.anthropic.com/v1"
PROSE = ("The river rises in the hills and runs north through three valleys before it meets the sea; "
         "its water feeds farms, two towns and a long line of old mills along the way. ") * 3
INTERRUPTED = runtime_messages.render("stream_interrupted", "en")
THINKING = {"type": "thinking", "thinking": "", "signature": "EqQBCkYIBRgCKkB+thinking=="}


def _claude(text="", *, size=20, tool=None, thinking=False, error=None, finished=True, unknown=False):
    events, at = [start()], 0
    if thinking:
        events += [block(0, {"type": "thinking", "thinking": "", "signature": ""}),
                   *([piece(0, type="a_future_delta", value="?")] if unknown else []),
                   piece(0, type="signature_delta", signature=THINKING["signature"]), stop(0)]
        at = 1
    if text:
        events.append(block(at, {"type": "text", "text": ""}))
        events += [piece(at, type="text_delta", text=text[i:i + size]) for i in range(0, len(text), size)]
        events.append(stop(at))
        at += 1
    if error:
        events.append(event("error", error={"type": error, "message": "Overloaded"}))
        return sse(*events)
    if tool:
        arguments = json.dumps(tool[1])
        events += [block(at, {"type": "tool_use", "id": "toolu_1", "name": tool[0], "input": {}}),
                   piece(at, type="input_json_delta", partial_json=arguments[:5]),
                   piece(at, type="input_json_delta", partial_json=arguments[5:]), stop(at)]
    if finished:
        events.append(end("tool_use" if tool else "end_turn"))
    return sse(*events)


class _Counted(httpx.AsyncByteStream):
    def __init__(self, body: bytes, sent: list):
        self.events, self.sent = [e for e in body.split(b"\n\n") if e], sent

    async def __aiter__(self):
        for e in self.events:
            self.sent.append(e)
            yield e + b"\n\n"
            await asyncio.sleep(0)


class _Search:
    def __init__(self):
        self.calls = 0

    async def execute(self, args):
        self.calls += 1
        return {"ok": True, "results": ["hit"]}


@pytest.fixture
def turn(execution_db, monkeypatch):
    monkeypatch.delenv("ARSLAN_TOOL_PROTOCOL", raising=False)

    async def en():
        return "en"
    monkeypatch.setattr(runtime_messages, "selected_locale", en)

    async def run(replies, *, tools=(), executors=None, sent=None, base=BASE):
        bodies = []

        def handler(request):
            body = json.loads(request.content)
            bodies.append(body)
            reply = replies[min(len(bodies), len(replies)) - 1]
            if not body.get("stream"):
                text = reply if isinstance(reply, str) else PROSE
                return httpx.Response(200, json=whole([{"type": "text", "text": text}]))
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  stream=_Counted(reply, sent if sent is not None else []))
        adapter = LLMAdapter("anthropic", "claude-opus-5-5", api_key="k", base_url=base)
        adapter._provider = AnthropicProvider("claude-opus-5-5", api_key="k", base_url=base,
                                              transport=httpx.MockTransport(handler))
        monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
        from server.registry import executors as registry
        for key, executor in (executors or {}).items():
            monkeypatch.setitem(registry.EXECUTORS, key, executor)

        async def resolve():
            return [{"key": key, "description": key} for key in tools]
        chunks, events = [], []
        result = await tool_loop.run_native(system="S", user_content="question", history=[], emit=events.append,
                                            on_chunk=chunks.append, resolve_tools=resolve)
        return result, chunks, events, bodies
    return run


async def test_a_long_claude_answer_goes_out_while_it_is_written(turn):
    sent, at_first = [], []
    original = tool_loop._TurnText.show

    def show(self, text):
        if not self.parts:
            at_first.append(len(sent))
        original(self, text)
    tool_loop._TurnText.show = show
    try:
        result, chunks, _, bodies = await turn([_claude(PROSE)], sent=sent)
    finally:
        tool_loop._TurnText.show = original
    total = len([e for e in _claude(PROSE).split(b"\n\n") if e])
    assert bodies[0]["stream"] is True
    assert at_first and at_first[0] < total                       # out before the model finished
    assert "".join(chunks) == result["final"] and result["final"].strip() == PROSE.strip()


async def test_the_thinking_a_step_returned_is_replayed_byte_for_byte(turn):
    search = _Search()
    result, chunks, _, bodies = await turn([_claude(tool=("web_search", {"query": "tides"}), thinking=True),
                                            _claude("High tide is at noon. " * 9)],
                                           tools=("web_search",), executors={"web_search": search})
    replayed = next(m for m in bodies[1]["messages"] if m["role"] == "assistant")["content"]
    assert replayed == [THINKING, {"type": "tool_use", "id": "toolu_1", "name": "web_search",
                                   "input": {"query": "tides"}}]
    assert search.calls == 1 and "".join(chunks) == result["final"]


async def test_another_anthropic_protocol_endpoint_answers_whole(turn):
    result, chunks, _, bodies = await turn([PROSE], base="https://claude-router.example/v1")
    assert "stream" not in bodies[0]                              # its streamed tool calls are not known
    assert "".join(chunks) == result["final"] and result["final"].strip() == PROSE.strip()


@pytest.mark.parametrize("kind", ["overloaded_error", "rate_limit_error", "api_error"])
async def test_a_retryable_error_after_text_went_out_is_not_resent(turn, kind):
    holder = {}
    host_run._failure.set(holder)
    result, chunks, _, bodies = await turn([_claude(PROSE, error=kind), _claude(PROSE)])
    joined = "".join(chunks)
    assert len(bodies) == 1 and joined == result["final"] and joined.endswith(INTERRUPTED)
    assert result["stop_reason"] == "model_error_after_text" and holder["kind"] == "model_error_after_text"


async def test_an_unknown_delta_in_a_reply_that_calls_a_tool_never_runs_the_tool_and_is_sent_once(turn):
    search = _Search()
    odd = _claude(tool=("web_search", {"query": "tides"}), thinking=True, unknown=True)
    with pytest.raises(model_call.ModelCallError) as failed:
        await turn([odd], tools=("web_search",), executors={"web_search": search})
    assert failed.value.kind == "unreadable" and failed.value.attempts == 1    # never resent (⓪Plan's review)
    assert search.calls == 0                                      # nothing ran on a reply we could not read


async def test_a_stream_that_only_pings_is_cut_by_the_turns_time():
    class Pings(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield start().encode()
            while True:
                await asyncio.sleep(0.05)
                yield event("ping").encode()

    provider = AnthropicProvider("claude-opus-5-5", api_key="k", base_url=BASE, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Pings())))
    started = asyncio.get_running_loop().time()
    with pytest.raises(model_call.ModelCallError) as cut:
        await model_call.call_with_recovery(
            lambda: provider.chat([{"role": "user", "content": "hi"}], stream=True), model_call.TurnRecovery(),
            remaining_s=lambda: 0.5)
    assert cut.value.kind == "stall" and asyncio.get_running_loop().time() - started < 5
