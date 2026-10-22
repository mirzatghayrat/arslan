"""K8c: Gemini's answer goes out while it is written (card K8; ⓪Plan's answers in the K8c plan).

Driven through the real LLMAdapter and GeminiProvider on a streamGenerateContent mock, so the text reaches
K8a's loop exactly as in production:
- Gemini on Google's own host streams; any other base URL answers whole (Q1);
- the parts a step returned, signatures included, are replayed exactly in the next request of the turn (Q3);
- once text went out, an error in the stream is not resent: the turn ends interrupted (Q4);
- a reply with a part this version does not know never runs its function call, and is sent once (Q3);
- a silent stream is still cut by the turn's time (Q2).
"""
import asyncio
import json

import httpx
import pytest

from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers.gemini_provider import GeminiProvider
from server.orchestrator import model_call, tool_loop
from server.services import host_run, runtime_messages
from tests.llm.test_k8c_gemini_stream import USAGE, chunk, sse, whole

BASE = "https://generativelanguage.googleapis.com/v1beta"
PROSE = ("The river rises in the hills and runs north through three valleys before it meets the sea; "
         "its water feeds farms, two towns and a long line of old mills along the way. ") * 3
INTERRUPTED = runtime_messages.render("stream_interrupted", "en")
CALL = {"functionCall": {"name": "web_search", "args": {"query": "tides"}}, "thoughtSignature": "c2lnMQ=="}


def _gemini(text="", *, size=20, call=None, error=None, finished=True, odd=False):
    out = [chunk({"text": text[i:i + size]}) for i in range(0, len(text), size)]
    if odd:
        out.append(chunk({"futurePart": {"x": 1}}))
    if error:
        out.append("data: " + json.dumps({"error": {"code": error, "message": "busy", "status": "UNAVAILABLE"}})
                   + "\r\n\r\n")
        return sse(*out)
    if finished:
        out.append(chunk(*([call] if call else [{"text": ""}]), finish="STOP", usage=USAGE))
    return sse(*out)


class _Counted(httpx.AsyncByteStream):
    def __init__(self, body: bytes, sent: list):
        self.events, self.sent = [e for e in body.split(b"\r\n\r\n") if e], sent

    async def __aiter__(self):
        for e in self.events:
            self.sent.append(e)
            yield e + b"\r\n\r\n"
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
        bodies, urls = [], []

        def handler(request):
            body = json.loads(request.content)
            bodies.append(body)
            urls.append(str(request.url))
            reply = replies[min(len(bodies), len(replies)) - 1]
            if ":streamGenerateContent" not in str(request.url):
                return httpx.Response(200, json=whole({"text": reply if isinstance(reply, str) else PROSE}))
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  stream=_Counted(reply, sent if sent is not None else []))
        adapter = LLMAdapter("gemini", "gemini-3-pro", api_key="k", base_url=base)
        adapter._provider = GeminiProvider("gemini-3-pro", api_key="k", base_url=base,
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
        return result, chunks, events, bodies, urls
    return run


async def test_a_long_gemini_answer_goes_out_while_it_is_written(turn):
    sent, at_first = [], []
    original = tool_loop._TurnText.show

    def show(self, text):
        if not self.parts:
            at_first.append(len(sent))
        original(self, text)
    tool_loop._TurnText.show = show
    try:
        result, chunks, _, _, urls = await turn([_gemini(PROSE)], sent=sent)
    finally:
        tool_loop._TurnText.show = original
    total = len([e for e in _gemini(PROSE).split(b"\r\n\r\n") if e])
    assert ":streamGenerateContent?alt=sse" in urls[0]
    assert at_first and at_first[0] < total                       # out before the model finished
    assert "".join(chunks) == result["final"] and result["final"].strip() == PROSE.strip()


async def test_the_parts_a_step_returned_are_replayed_exactly(turn):
    search = _Search()
    result, chunks, _, bodies, _ = await turn([_gemini("Checking.", call=CALL), _gemini("High tide is at noon. " * 9)],
                                              tools=("web_search",), executors={"web_search": search})
    replayed = next(c for c in bodies[1]["contents"] if c["role"] == "model")["parts"]
    assert replayed == [{"text": "Checking."}, CALL]               # every part in order, the signature on its own
    assert search.calls == 1 and "".join(chunks) == result["final"]


async def test_another_base_url_answers_whole(turn):
    result, chunks, _, _, urls = await turn([PROSE], base="https://gemini-router.example/v1beta")
    assert ":generateContent" in urls[0] and ":streamGenerateContent" not in urls[0]
    assert "".join(chunks) == result["final"] and result["final"].strip() == PROSE.strip()


@pytest.mark.parametrize("code", [503, 429, 500])
async def test_an_error_after_text_went_out_is_not_resent(turn, code):
    holder = {}
    host_run._failure.set(holder)
    result, chunks, _, bodies, _ = await turn([_gemini(PROSE, error=code), _gemini(PROSE)])
    joined = "".join(chunks)
    assert len(bodies) == 1 and joined == result["final"] and joined.endswith(INTERRUPTED)
    assert result["stop_reason"] == "model_error_after_text" and holder["kind"] == "model_error_after_text"


async def test_a_reply_with_an_unknown_part_never_runs_its_call_and_is_sent_once(turn):
    search = _Search()
    with pytest.raises(model_call.ModelCallError) as failed:
        await turn([_gemini(call=CALL, odd=True)], tools=("web_search",), executors={"web_search": search})
    assert failed.value.kind == "unreadable" and failed.value.attempts == 1 and search.calls == 0


async def test_a_silent_stream_is_cut_by_the_turns_time():
    class Silent(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield chunk({"text": "a"}).encode()
            await asyncio.sleep(3)              # silence well past the turn's 1 s budget
            yield b""

    provider = GeminiProvider("gemini-3-pro", api_key="k", base_url=BASE, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Silent())))
    started = asyncio.get_running_loop().time()
    with pytest.raises(model_call.ModelCallError) as cut:
        await model_call.call_with_recovery(
            lambda: provider.chat([{"role": "user", "content": "hi"}], stream=True), model_call.TurnRecovery(),
            remaining_s=lambda: 0.5)
    assert cut.value.kind == "stall" and asyncio.get_running_loop().time() - started < 5
