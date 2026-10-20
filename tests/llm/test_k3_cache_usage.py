"""K3: cache reads and writes are counted, and the context ring reads the whole input.

Anthropic's `input_tokens` leaves out what was read from or written to the cache, so on Claude the
ring ("the last call's input") shrank as soon as the cache hit. The whole input is now
uncached + cache read + cache write there; OpenAI-compatible endpoints and Gemini already report it
whole. The reply's usage carries the cache reads and the whole input, so the footer can show a hit
rate. `tokens_in` and the price stay as they were (pricing cached tokens is a separate change).
"""
import json

import httpx
import pytest

from arslan.llm import usage_sink
from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers.anthropic_provider import AnthropicProvider
from arslan.llm.usage_weight import cache_split


@pytest.mark.parametrize("usage, expected", [
    ({"input_tokens": 100, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 50, "output_tokens": 9},
     {"cache_read": 900, "cache_write": 50, "input_total": 1050}),
    ({"input_tokens": 100, "output_tokens": 9},                                     # Claude, nothing cached
     {"cache_read": 0, "cache_write": 0, "input_total": 100}),
    ({"prompt_tokens": 1000, "completion_tokens": 9, "prompt_tokens_details": {"cached_tokens": 800}},
     {"cache_read": 800, "cache_write": None, "input_total": 1000}),
    ({"prompt_tokens": 1000, "completion_tokens": 9, "prompt_cache_hit_tokens": 700,
      "prompt_cache_miss_tokens": 300}, {"cache_read": 700, "cache_write": None, "input_total": 1000}),
    ({"promptTokenCount": 1000, "candidatesTokenCount": 9, "cachedContentTokenCount": 600},
     {"cache_read": 600, "cache_write": None, "input_total": 1000}),
    ({"prompt_tokens": 1000, "completion_tokens": 9}, None),                         # no cache report
])
def test_each_providers_cache_report_is_read(usage, expected):
    assert cache_split(usage) == expected


def _claude(replies):
    def handler(request):
        return httpx.Response(200, json=replies.pop(0))
    adapter = LLMAdapter("anthropic", "claude-opus-5-5")
    adapter._provider = AnthropicProvider("claude-opus-5-5", api_key="k", transport=httpx.MockTransport(handler))
    return adapter


def _reply(uncached, read, written):
    return {"role": "assistant", "stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": uncached, "cache_read_input_tokens": read,
                      "cache_creation_input_tokens": written, "output_tokens": 5}}


async def test_on_claude_the_ring_reads_the_whole_input_and_the_cache_reads_add_up():
    adapter = _claude([_reply(100, 0, 900), _reply(40, 1000, 60)])
    with usage_sink.collecting():
        await adapter.chat("S", "first")
        await adapter.chat("S", "second")
        detail, last = usage_sink.detail(), usage_sink.last_input()
    assert last == 40 + 1000 + 60                      # the last call's whole input
    assert detail["cache_read"] == 1000 and detail["input_total"] == 1000 + 1100
    assert detail["tokens_in"] == 140                  # unchanged: what Anthropic calls input_tokens


async def test_a_streamed_claude_reply_counts_its_cache_too():
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 30, "cache_read_input_tokens": 700,
                                                        "cache_creation_input_tokens": 0, "output_tokens": 1}}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}},
        {"type": "message_delta", "usage": {"output_tokens": 4}},
    ]
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events)

    def handler(request):
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    adapter = LLMAdapter("anthropic", "claude-opus-5-5")
    adapter._provider = AnthropicProvider("claude-opus-5-5", api_key="k", transport=httpx.MockTransport(handler))
    with usage_sink.collecting():
        assert "".join([piece async for piece in adapter.chat_stream("S", "hi")]) == "ok"
        detail, last = usage_sink.detail(), usage_sink.last_input()
    assert last == 730 and detail["cache_read"] == 700 and detail["input_total"] == 730


def test_the_reply_frame_carries_cache_reads_and_the_whole_input():
    from server.orchestrator import arslan
    with usage_sink.collecting():
        usage_sink.report_detail(tokens_in=40, tokens_out=5, model="claude-opus-5-5", provider="anthropic",
                                 cache_read=1000, cache_write=60, input_total=1100)
        frame = arslan._usage_frame(usage_sink.detail())
    assert frame["cache_read"] == 1000 and frame["input_total"] == 1100 and frame["last_input"] == 1100


def test_without_a_cache_report_the_frame_says_nothing_about_the_cache():
    from server.orchestrator import arslan
    with usage_sink.collecting():
        usage_sink.report_detail(tokens_in=400, tokens_out=5, model="m", provider="ollama")
        frame = arslan._usage_frame(usage_sink.detail())
    assert frame["cache_read"] is None and frame["input_total"] == 400 and frame["last_input"] == 400
