"""K8b: a Claude reply streamed as Messages SSE is assembled into exactly the reply the non-streamed API
returns (card K8, K8b; ⓪Plan's answers in the K8b plan).

The fixtures follow the documented event shapes: message_start (the message, its usage and
input_transformations), content_block_start / _delta (text_delta, input_json_delta, thinking_delta,
signature_delta, citations_delta) / _stop, message_delta (stop reason, cumulative usage, context_management),
message_stop, ping and error. For each, the streamed parse equals the non-streamed one, thinking blocks and
signatures included (they are replayed byte for byte, K1); only answer text reaches `on_text`.
"""
import asyncio
import json

import httpx
import pytest

from arslan.llm import anthropic_stream, stream_assembly
from arslan.llm.providers.anthropic_provider import AnthropicProvider

BASE = "https://api.anthropic.com/v1"
START_USAGE = {"input_tokens": 120, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 900,
               "output_tokens": 1}


def event(kind, **body):
    return f"event: {kind}\ndata: {json.dumps({'type': kind, **body})}\n\n"


def sse(*events):
    return "".join(events).encode()


def start(**extra):
    message = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
               "content": [], "stop_reason": None, "stop_sequence": None, "usage": dict(START_USAGE), **extra}
    return event("message_start", message=message)


def block(index, content_block):
    return event("content_block_start", index=index, content_block=content_block)


def piece(index, **delta):
    return event("content_block_delta", index=index, delta=delta)


def stop(index):
    return event("content_block_stop", index=index)


def end(reason="end_turn", output=42, **extra):
    return (event("message_delta", delta={"stop_reason": reason, "stop_sequence": None},
                  usage={"output_tokens": output}, **extra) + event("message_stop"))


def whole(content, reason="end_turn", output=42, **extra):
    """The same reply as the non-streamed API returns it."""
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": content,
            "stop_reason": reason, "stop_sequence": None, "usage": {**START_USAGE, "output_tokens": output}, **extra}


class _Body(httpx.AsyncByteStream):
    def __init__(self, data: bytes, gaps: list[float] | None = None):
        self.parts = [p + b"\n\n" for p in data.split(b"\n\n") if p]
        self.gaps = gaps or []

    async def __aiter__(self):
        for i, part in enumerate(self.parts):
            if i < len(self.gaps):
                await asyncio.sleep(self.gaps[i])
            yield part


async def assemble(data: bytes, on_text=None, gaps=None):
    response = httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=_Body(data, gaps))
    return await anthropic_stream.assemble(response, on_text)


def parse(data):
    return AnthropicProvider("claude-opus-5-5", api_key="k", base_url=BASE)._parse_response(data)


def same(streamed, non_streamed):
    a, b = parse(streamed), parse(non_streamed)
    assert (a.content, a.tool_calls, a.finish_reason, a.usage, a.continuation, a.input_transformations) == (
        b.content, b.tool_calls, b.finish_reason, b.usage, b.continuation, b.input_transformations)


async def test_a_text_answer_is_the_same_streamed_and_only_its_text_reaches_on_text():
    shown = []
    data = sse(start(), event("ping"), block(0, {"type": "text", "text": ""}), piece(0, type="text_delta", text="Hel"),
               piece(0, type="text_delta", text="lo."), stop(0), end())
    streamed = await assemble(data, shown.append)
    assert streamed == whole([{"type": "text", "text": "Hello."}])
    same(streamed, whole([{"type": "text", "text": "Hello."}]))
    assert shown == ["Hel", "lo."]


async def test_thinking_its_signature_text_and_a_tool_call_in_pieces_are_the_same_streamed():
    shown = []
    data = sse(start(), block(0, {"type": "thinking", "thinking": "", "signature": ""}),
               piece(0, type="thinking_delta", thinking="Check the "), piece(0, type="thinking_delta", thinking="notes."),
               piece(0, type="signature_delta", signature="EqQBCkYIBRgCKkB=="), stop(0),
               block(1, {"type": "text", "text": ""}), piece(1, type="text_delta", text="Reading it."), stop(1),
               block(2, {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {}}),
               piece(2, type="input_json_delta", partial_json=""), piece(2, type="input_json_delta", partial_json='{"pa'),
               piece(2, type="input_json_delta", partial_json='th": "notes.md"}'), stop(2), end("tool_use", 77))
    expected = whole([{"type": "thinking", "thinking": "Check the notes.", "signature": "EqQBCkYIBRgCKkB=="},
                      {"type": "text", "text": "Reading it."},
                      {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "notes.md"}}],
                     "tool_use", 77)
    streamed = await assemble(data, shown.append)
    assert streamed == expected
    same(streamed, expected)
    assert shown == ["Reading it."]                              # never the thinking, never the arguments


async def test_redacted_thinking_a_tool_call_without_arguments_and_citations_are_the_same_streamed():
    cite = {"type": "char_location", "cited_text": "x", "document_index": 0, "start_char_index": 0, "end_char_index": 1}
    data = sse(start(), block(0, {"type": "redacted_thinking", "data": "EmwKAhgB"}), stop(0),
               block(1, {"type": "text", "text": ""}), piece(1, type="text_delta", text="See "),
               piece(1, type="citations_delta", citation=cite), stop(1),
               block(2, {"type": "tool_use", "id": "toolu_2", "name": "list_folder", "input": {}}), stop(2),
               end("tool_use"))
    expected = whole([{"type": "redacted_thinking", "data": "EmwKAhgB"},
                      {"type": "text", "text": "See ", "citations": [cite]},
                      {"type": "tool_use", "id": "toolu_2", "name": "list_folder", "input": {}}], "tool_use")
    streamed = await assemble(data)
    assert streamed == expected
    same(streamed, expected)


async def test_what_the_api_reports_about_the_conversation_arrives_as_without_streaming():
    dropped = [{"type": "thinking_dropped", "path": "messages.3.content.0", "reason": "prefix_binding_mismatch"}]
    edits = {"applied_edits": [{"type": "clear_tool_uses_20250919", "cleared_tool_uses": 4,
                                "cleared_input_tokens": 41_000}]}
    data = sse(start(input_transformations=dropped), block(0, {"type": "text", "text": ""}),
               piece(0, type="text_delta", text="Done."), stop(0), end(context_management=edits))
    expected = whole([{"type": "text", "text": "Done."}], input_transformations=dropped, context_management=edits)
    streamed = await assemble(data)
    assert streamed == expected
    same(streamed, expected)


async def test_a_ping_keeps_a_silent_think_alive_and_silence_does_not(monkeypatch):
    monkeypatch.setattr(stream_assembly, "IDLE_S", 0.2)
    pings = sse(start(), *[event("ping")] * 6, block(0, {"type": "text", "text": ""}),
                piece(0, type="text_delta", text="ok"), stop(0), end())
    assert (await assemble(pings, gaps=[0, *[0.1] * 6]))["content"] == [{"type": "text", "text": "ok"}]
    with pytest.raises(stream_assembly.StreamStalled):
        await assemble(sse(start(), block(0, {"type": "text", "text": ""}), stop(0), end()), gaps=[0, 0.35])


@pytest.mark.parametrize("kind,status", [("overloaded_error", 529), ("rate_limit_error", 429), ("api_error", 500),
                                         ("invalid_request_error", 400), ("a_new_kind", 500)])
async def test_an_error_in_the_stream_is_raised_as_the_status_its_kind_means(kind, status):
    data = sse(start(), block(0, {"type": "text", "text": ""}), piece(0, type="text_delta", text="Partial"),
               event("error", error={"type": kind, "message": "Overloaded"}))
    with pytest.raises(httpx.HTTPStatusError) as raised:
        await assemble(data)
    assert raised.value.response.status_code == status and kind in str(raised.value)


async def test_a_stream_that_ends_before_message_stop_is_never_taken_as_an_answer():
    data = sse(start(), block(0, {"type": "text", "text": ""}), piece(0, type="text_delta", text="Half an"))
    with pytest.raises(httpx.RemoteProtocolError):
        await assemble(data)


async def test_an_unknown_delta_loses_the_verbatim_replay_of_a_pure_answer():
    """⓪Plan's Q5: a block assembled with a delta we do not know is never replayed as if it were whole."""
    data = sse(start(), block(0, {"type": "thinking", "thinking": "", "signature": ""}),
               piece(0, type="a_future_delta", value="?"), piece(0, type="signature_delta", signature="sig"), stop(0),
               block(1, {"type": "text", "text": ""}), piece(1, type="text_delta", text="Answer."), stop(1), end())
    response = parse(await assemble(data))
    assert response.content == "Answer." and response.continuation is None


async def test_an_unknown_delta_in_a_reply_that_calls_a_tool_fails_cleanly():
    """⓪Plan's Q5: without its thinking the tool call's next request may be refused; so the step fails here
    (a protocol error: resent only while nothing was shown) instead of sending a request that could be a 400."""
    data = sse(start(), block(0, {"type": "thinking", "thinking": "", "signature": ""}),
               piece(0, type="a_future_delta", value="?"), stop(0),
               block(1, {"type": "tool_use", "id": "toolu_3", "name": "read_file", "input": {}}),
               piece(1, type="input_json_delta", partial_json="{}"), stop(1), end("tool_use"))
    with pytest.raises(httpx.RemoteProtocolError, match="unknown"):
        await assemble(data)
