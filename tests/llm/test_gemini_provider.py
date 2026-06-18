"""Tests for the native GeminiProvider (Tier 2)."""
import json

import httpx

from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers.gemini_provider import GeminiProvider


def test_provider_name_and_default_base_url():
    p = GeminiProvider(model="gemini-2.0-flash", api_key="k")
    assert p.provider_name == "gemini"
    assert p.base_url == GeminiProvider.DEFAULT_BASE_URL


def test_to_contents_maps_roles_and_splits_system():
    p = GeminiProvider(model="gemini-2.0-flash")
    messages = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo"},
    ]
    system, contents = p._to_contents(messages)
    assert system == "SYS"
    assert contents == [
        {"role": "user", "parts": [{"text": "hi"}]},
        {"role": "model", "parts": [{"text": "yo"}]},  # assistant -> model
    ]


def test_parse_response_joins_parts():
    p = GeminiProvider(model="gemini-2.0-flash")
    data = {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": "Hello "}, {"text": "world"}]}}
        ],
        "usageMetadata": {"totalTokenCount": 7},
    }
    resp = p._parse_response(data)
    assert resp.content == "Hello world"
    assert resp.usage["totalTokenCount"] == 7


async def test_chat_sends_gemini_format():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                  "usageMetadata": {"totalTokenCount": 2}},
        )

    p = GeminiProvider(model="gemini-2.0-flash", api_key="g-key",
                       transport=httpx.MockTransport(handler))
    resp = await p.chat(
        [{"role": "system", "content": "SYS"}, {"role": "user", "content": "hi"}],
        temperature=0.4,
    )

    assert resp.content == "ok"
    assert ":generateContent" in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == "g-key"
    assert captured["payload"]["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert captured["payload"]["contents"][0]["role"] == "user"


async def test_chat_stream_yields_text_deltas():
    sse = (
        'data: {"candidates":[{"content":{"parts":[{"text":"He"}]}}]}\n\n'
        'data: {"candidates":[{"content":{"parts":[{"text":"llo"}]}}]}\n\n'
    )

    def handler(request):
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    p = GeminiProvider(model="gemini-2.0-flash", api_key="k",
                       transport=httpx.MockTransport(handler))
    out = []
    async for piece in p.chat_stream([{"role": "user", "content": "hi"}]):
        out.append(piece)
    assert "".join(out) == "Hello"


def test_adapter_registers_gemini_provider():
    adapter = LLMAdapter("gemini", "gemini-2.0-flash", api_key="k")
    assert isinstance(adapter._provider, GeminiProvider)
