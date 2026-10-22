"""K8c: a Gemini reply streamed from `:streamGenerateContent?alt=sse` is assembled into one response that
parses as the non-streamed reply (card K8, K8c; ⓪Plan's answers in the K8c plan).

The fixtures follow the documented chunk shape: each `data:` line is a partial GenerateContentResponse
(`candidates[0].content.parts`: text, `thought: true` text, `functionCall`, `thoughtSignature` on the part it
belongs to), `finishReason` on the last, cumulative `usageMetadata`. Parts are kept in order and as sent, so
every signature stays on its own part; the stream splits text into more parts than a whole reply has, so
"the same parse" means the same text, calls, finish reason, usage and the same calls with their signatures.
Only non-thought text reaches `on_text`.
"""
import asyncio
import json

import httpx
import pytest

from arslan.llm import gemini_stream, stream_assembly
from arslan.llm.providers.gemini_provider import GeminiProvider

USAGE = {"promptTokenCount": 40, "candidatesTokenCount": 12, "totalTokenCount": 52, "thoughtsTokenCount": 30}


def chunk(*parts, finish=None, usage=None, **extra):
    candidate = {"content": {"role": "model", "parts": list(parts)}, "index": 0}
    if finish:
        candidate["finishReason"] = finish
    body = {"candidates": [candidate], "modelVersion": "gemini-3-pro", "responseId": "r1", **extra}
    if usage:
        body["usageMetadata"] = usage
    return "data: " + json.dumps(body) + "\r\n\r\n"


def sse(*chunks):
    return "".join(chunks).encode()


def whole(*parts, finish="STOP", usage=USAGE):
    return {"candidates": [{"content": {"role": "model", "parts": list(parts)}, "index": 0, "finishReason": finish}],
            "usageMetadata": usage, "modelVersion": "gemini-3-pro", "responseId": "r1"}


class _Body(httpx.AsyncByteStream):
    def __init__(self, data: bytes, gaps=None):
        self.parts = [p + b"\r\n\r\n" for p in data.split(b"\r\n\r\n") if p]
        self.gaps = gaps or []

    async def __aiter__(self):
        for i, part in enumerate(self.parts):
            if i < len(self.gaps):
                await asyncio.sleep(self.gaps[i])
            yield part


async def assemble(data: bytes, on_text=None, gaps=None):
    response = httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=_Body(data, gaps))
    return await gemini_stream.assemble(response, on_text)


def parse(data):
    return GeminiProvider("gemini-3-pro", api_key="k")._parse_response(data)


def meaning(response):
    calls = [(c["function"]["name"], c["function"]["arguments"], c["provider_id"]) for c in response.tool_calls]
    signed = [(p.get("functionCall", {}).get("name"), p.get("thoughtSignature"))
              for p in (response.provider_content or {}).get("parts", []) if "thoughtSignature" in p]
    return response.content, calls, response.finish_reason, response.usage, signed


async def test_a_text_answer_is_the_same_streamed_and_only_its_text_reaches_on_text():
    shown = []
    data = sse(chunk({"text": "Hel"}), chunk({"text": "lo."}), chunk({"text": ""}, finish="STOP", usage=USAGE))
    streamed = await assemble(data, shown.append)
    assert meaning(parse(streamed)) == meaning(parse(whole({"text": "Hello."})))
    assert shown == ["Hel", "lo."]


async def test_two_calls_in_one_chunk_with_a_signature_are_the_same_streamed_and_kept_in_order():
    calls = [{"functionCall": {"name": "web_search", "args": {"query": "tides"}}, "thoughtSignature": "c2lnMQ=="},
             {"functionCall": {"name": "read_file", "args": {"path": "notes.md"}}}]
    data = sse(chunk({"text": "Checking two things."}), chunk(*calls, finish="STOP", usage=USAGE))
    streamed = parse(await assemble(data))
    assert meaning(streamed) == meaning(parse(whole({"text": "Checking two things."}, *calls)))
    assert streamed.provider_content["parts"] == [{"text": "Checking two things."}, *calls]


async def test_a_signature_on_a_trailing_empty_text_part_stays_on_that_part():
    parts = [{"text": "Let me"}, {"text": " check."},
             {"functionCall": {"name": "list_dir", "args": {"path": "."}}}, {"text": "", "thoughtSignature": "dGFpbA=="}]
    data = sse(chunk(parts[0]), chunk(parts[1]), chunk(parts[2]), chunk(parts[3], finish="STOP", usage=USAGE))
    streamed = parse(await assemble(data))
    assert streamed.provider_content["parts"] == parts                      # exactly as received, in order
    assert meaning(streamed)[1] == [("list_dir", {"path": "."}, None)]


async def test_thought_parts_never_reach_on_text_or_the_answer():
    shown = []
    data = sse(chunk({"text": "Weighing the options", "thought": True}), chunk({"text": "Pick B."}),
               chunk({"text": ""}, finish="STOP", usage=USAGE))
    response = parse(await assemble(data, shown.append))
    assert shown == ["Pick B."] and response.content == "Pick B."


async def test_a_prompt_blocked_before_any_candidate_is_an_answer_with_nothing_in_it():
    data = sse("data: " + json.dumps({"promptFeedback": {"blockReason": "SAFETY"}, "usageMetadata": USAGE}) + "\r\n\r\n")
    response = parse(await assemble(data))
    assert response.content is None and response.tool_calls == []


async def test_safety_mid_answer_keeps_what_was_written_and_says_content_filter():
    data = sse(chunk({"text": "Here is the start"}), chunk({"text": ""}, finish="SAFETY", usage=USAGE))
    response = parse(await assemble(data))
    assert response.content == "Here is the start" and response.finish_reason == "content_filter"


@pytest.mark.parametrize("code,status", [(429, 429), (503, 503), (500, 500), (None, 500)])
async def test_an_error_in_the_stream_is_raised_as_its_status(code, status):
    error = {"message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED", **({"code": code} if code else {})}
    data = sse(chunk({"text": "Partial"}), "data: " + json.dumps({"error": error}) + "\r\n\r\n")
    with pytest.raises(httpx.HTTPStatusError) as raised:
        await assemble(data)
    assert raised.value.response.status_code == status


async def test_a_stream_that_ends_before_its_finish_reason_is_never_an_answer():
    with pytest.raises(httpx.RemoteProtocolError):
        await assemble(sse(chunk({"text": "Half an"})))


async def test_an_unknown_part_in_a_reply_that_calls_a_function_is_refused():
    """⓪Plan's Q3: the call does not run on a reply that may not be what the API sent."""
    data = sse(chunk({"futurePart": {"x": 1}}), chunk({"functionCall": {"name": "list_dir", "args": {}}},
                                                       finish="STOP", usage=USAGE))
    with pytest.raises(stream_assembly.UnreadableReply):
        await assemble(data)


async def test_a_line_that_does_not_parse_in_a_reply_that_calls_a_function_is_refused():
    data = sse(chunk({"text": "ok"}), "data: {not json\r\n\r\n",
               chunk({"functionCall": {"name": "list_dir", "args": {}}}, finish="STOP", usage=USAGE))
    with pytest.raises(stream_assembly.UnreadableReply):
        await assemble(data)


async def test_an_unknown_part_in_a_pure_answer_still_answers():
    """No function call: nothing of this reply is replayed (provider_content is for calls only)."""
    data = sse(chunk({"futurePart": {"x": 1}}), chunk({"text": "Fine."}, finish="STOP", usage=USAGE))
    response = parse(await assemble(data))
    assert response.content == "Fine." and response.provider_content is None


async def test_silence_past_the_gemini_idle_bound_is_a_stall(monkeypatch):
    """Gemini sends nothing while it thinks: its own idle bound (Q2), here shortened."""
    monkeypatch.setattr(gemini_stream, "IDLE_S", 0.2)
    with pytest.raises(stream_assembly.StreamStalled):
        await assemble(sse(chunk({"text": "a"}), chunk({"text": "b"}, finish="STOP")), gaps=[0, 0.35])
    assert gemini_stream.IDLE_S == 0.2 and (await assemble(sse(chunk({"text": "a"}, finish="STOP"))))["candidates"]
