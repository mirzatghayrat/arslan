"""K8a C1: the answer's text is handed on as it arrives (card K8).

Before K8, streaming existed only for the idle watchdog: `stream_assembly.assemble` read the whole SSE
body and the loop got one complete reply. Now an `on_text` callback gets each `content` delta as it
arrives, through the assembler, `OpenAIProvider.chat(stream=True)` and `adapter.chat_trajectory`:
- only the answer's text: reasoning and tool-call arguments never reach it;
- the complete reply is returned as before, and its content is exactly the pieces joined;
- an endpoint that does not stream (a local server), or a streaming one that answers with plain JSON,
  never calls it: the loop then shows the reply whole, as today;
- a resend after an error status (param_heal) happens before any body is read, so no text precedes it.
"""
import json

import httpx

from arslan.llm import stream_assembly
from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers.openai_provider import OpenAIProvider
from tests.llm.test_stream_assembly_s7 import BASE, delta, finish, provider, sse, stream_response


def _answer(*pieces, tool=False):
    frames = [delta(role="assistant", reasoning_content="thinking, never shown")]
    frames += [delta(content=p) for p in pieces]
    if tool:
        frames.append(delta(tool_calls=[{"index": 0, "id": "c1", "type": "function",
                                         "function": {"name": "read_file", "arguments": '{"path": "a"}'}}]))
    frames.append(finish("tool_calls" if tool else "stop", {"prompt_tokens": 3, "completion_tokens": 2}))
    return sse(*frames)


def _adapter(p):
    adapter = LLMAdapter("openai", "deepseek-v4-flash", api_key="k", base_url=BASE)
    adapter._provider = p
    return adapter


def test_the_assembler_hands_on_content_deltas_only():
    got = []
    assembler = stream_assembly.StreamAssembler(on_text=got.append)
    for frame in (delta(reasoning_content="hmm"), delta(content="Hel"), delta(content="lo"),
                  delta(tool_calls=[{"index": 0, "id": "c", "function": {"name": "x", "arguments": "{}"}}])):
        assembler.feed(frame)
    assert got == ["Hel", "lo"] and assembler.result()["choices"][0]["message"]["content"] == "Hello"


async def test_the_provider_hands_on_each_piece_and_returns_the_whole_reply():
    got = []
    p = provider(lambda request: stream_response(_answer("The ", "answer ", "is 42.")))
    resp = await p.chat([{"role": "user", "content": "q"}], stream=True, on_text=got.append)
    assert got == ["The ", "answer ", "is 42."] and resp.content == "".join(got)


async def test_text_before_a_tool_call_is_handed_on_too():
    got = []
    p = provider(lambda request: stream_response(_answer("Let me look.", tool=True)))
    resp = await p.chat([{"role": "user", "content": "q"}], stream=True, on_text=got.append)
    assert got == ["Let me look."] and resp.tool_calls


async def test_the_adapter_passes_it_down_only_where_the_endpoint_streams():
    got = []
    streaming = _adapter(provider(lambda request: stream_response(_answer("Hi ", "there."))))
    resp = await streaming.chat_trajectory("sys", [{"role": "user", "content": "q"}], on_text=got.append)
    assert got == ["Hi ", "there."] and resp.content == "Hi there."

    local_body = {"choices": [{"message": {"role": "assistant", "content": "whole"}, "finish_reason": "stop"}],
                  "usage": {}}
    local = _adapter(OpenAIProvider(model="m", api_key="k", base_url="http://127.0.0.1:1234/v1",
                                    transport=httpx.MockTransport(lambda r: httpx.Response(200, json=local_body))))
    got.clear()
    resp = await local.chat_trajectory("sys", [{"role": "user", "content": "q"}], on_text=got.append)
    assert got == [] and resp.content == "whole"


async def test_plain_json_from_a_streaming_endpoint_is_never_handed_on():
    got = []
    body = {"choices": [{"message": {"role": "assistant", "content": "whole"}, "finish_reason": "stop"}], "usage": {}}
    p = provider(lambda request: httpx.Response(200, json=body))
    resp = await p.chat([{"role": "user", "content": "q"}], stream=True, on_text=got.append)
    assert got == [] and resp.content == "whole"


async def test_a_resend_after_an_error_status_comes_before_any_text():
    got, sent = [], []

    def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) == 1:          # a parameter this endpoint refuses: param_heal drops it and resends
            return httpx.Response(400, json={"error": {"message": "Unsupported parameter: 'temperature'"}})
        return stream_response(_answer("Only ", "once."))
    p = provider(handler, base=BASE)
    resp = await p.chat([{"role": "user", "content": "q"}], stream=True, on_text=got.append)
    assert len(sent) == 2 and got == ["Only ", "once."] and resp.content == "Only once."
