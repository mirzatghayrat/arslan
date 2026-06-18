"""Tests for the native AnthropicProvider (Tier 1)."""
import json

import httpx

from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers.anthropic_provider import AnthropicProvider


def test_provider_name_and_default_base_url():
    p = AnthropicProvider(model="claude-opus-4-8", api_key="k")
    assert p.provider_name == "anthropic"
    assert p.base_url == AnthropicProvider.DEFAULT_BASE_URL


def test_split_system_separates_system_from_conversation():
    p = AnthropicProvider(model="claude-opus-4-8")
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "more"},
    ]
    system, convo = p._split_system(messages)
    assert system == "You are helpful."
    assert convo == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "more"},
    ]


def test_parse_response_joins_text_blocks():
    p = AnthropicProvider(model="claude-opus-4-8")
    data = {
        "role": "assistant",
        "content": [{"type": "text", "text": "Hello "}, {"type": "text", "text": "world"}],
        "usage": {"input_tokens": 5, "output_tokens": 2},
    }
    resp = p._parse_response(data)
    assert resp.content == "Hello world"
    assert resp.usage["output_tokens"] == 2


async def test_chat_sends_anthropic_format():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"role": "assistant", "content": [{"type": "text", "text": "ok"}],
                  "usage": {"input_tokens": 1, "output_tokens": 1}},
        )

    p = AnthropicProvider(model="claude-opus-4-8", api_key="sk-ant",
                          transport=httpx.MockTransport(handler))
    messages = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "hi"},
    ]
    resp = await p.chat(messages, temperature=0.5)

    assert resp.content == "ok"
    assert captured["url"].endswith("/messages")
    assert captured["headers"]["x-api-key"] == "sk-ant"
    assert captured["headers"]["anthropic-version"]
    # system is a TOP-LEVEL field, not a message
    assert captured["payload"]["system"] == "SYS"
    assert {"role": "system"} not in [{"role": m["role"]} for m in captured["payload"]["messages"]]
    assert "max_tokens" in captured["payload"]


async def test_chat_stream_yields_text_deltas():
    sse = (
        'data: {"type":"message_start"}\n\n'
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"He"}}\n\n'
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"llo"}}\n\n'
        'data: {"type":"message_stop"}\n\n'
    )

    def handler(request):
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    p = AnthropicProvider(model="claude-opus-4-8", api_key="k",
                          transport=httpx.MockTransport(handler))
    out = []
    async for piece in p.chat_stream([{"role": "user", "content": "hi"}]):
        out.append(piece)
    assert "".join(out) == "Hello"


def test_adapter_registers_anthropic_provider():
    adapter = LLMAdapter("anthropic", "claude-opus-4-8", api_key="k")
    assert isinstance(adapter._provider, AnthropicProvider)
