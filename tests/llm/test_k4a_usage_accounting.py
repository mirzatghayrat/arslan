"""K4a: a streamed answer is charged the way a non-streamed one is (cache reads at 0.1).

Before, `LLMAdapter.chat_stream` debited `tokens_in + tokens_out`: for DeepSeek `prompt_tokens`
includes the cache hits, so a cached context was charged at full weight; for Anthropic `input_tokens`
leaves out cache reads and writes, so a 90k cached context was charged about nothing.
"""
import json

import httpx

from arslan import execution_budget as eb
from arslan.llm.adapter import LLMAdapter


def _sse(events):
    return "\n".join(f"data: {json.dumps(e)}\n" for e in events) + "\n"


def _deepseek_adapter(usage):
    from arslan.llm.providers.openai_provider import OpenAIProvider
    body = _sse([{"choices": [{"delta": {"content": "Hello"}}]}, {"choices": [], "usage": usage}]) + "data: [DONE]\n\n"

    def handler(request):
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    adapter = LLMAdapter("openai", "deepseek-chat", api_key="k", base_url="https://api.deepseek.com/v1")
    adapter._provider = OpenAIProvider(model="deepseek-chat", api_key="k", base_url="https://api.deepseek.com/v1",
                                       transport=httpx.MockTransport(handler))
    return adapter


ANTHROPIC_START = {"input_tokens": 1000, "cache_read_input_tokens": 90_000, "cache_creation_input_tokens": 2000,
                   "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 2000},
                   "output_tokens": 1}


def _anthropic_adapter():
    from arslan.llm.providers.anthropic_provider import AnthropicProvider
    events = [{"type": "message_start", "message": {"usage": ANTHROPIC_START}},
              {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}},
              {"type": "message_delta", "usage": {"output_tokens": 500}},
              {"type": "message_stop"}]
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)

    def handler(request):
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    adapter = LLMAdapter("anthropic", "claude-sonnet-5")
    adapter._provider = AnthropicProvider("claude-sonnet-5", api_key="k", transport=httpx.MockTransport(handler))
    return adapter


async def _charged(adapter) -> int:
    with eb.scope(eb.run_budget()) as budget:
        assert "".join([piece async for piece in adapter.chat_stream("S", "hi")]) == "Hello"
        return budget.tokens


async def test_a_streamed_deepseek_answer_charges_its_cache_hits_at_a_tenth():
    usage = {"prompt_tokens": 100_000, "prompt_cache_hit_tokens": 90_000, "prompt_cache_miss_tokens": 10_000,
             "completion_tokens": 500, "total_tokens": 100_500}
    assert await _charged(_deepseek_adapter(usage)) == 10_000 + 9_000 + 500          # was 100 500


async def test_a_streamed_anthropic_answer_charges_its_cache_reads_and_writes():
    assert await _charged(_anthropic_adapter()) == 1000 + 2000 + 9_000 + 500          # was 1 500


async def test_the_provider_keeps_the_streams_whole_usage():
    adapter = _anthropic_adapter()
    await _charged(adapter)
    assert adapter._provider._last_stream_usage["usage"] == {**ANTHROPIC_START, "output_tokens": 500}


async def test_a_plain_streamed_turn_with_a_large_cached_context_is_debited_at_a_tenth(monkeypatch):
    """⓪Plan: the tool-less streamed path of the loop (stream_without_tools) charges as above."""
    from server.orchestrator import tool_loop
    adapter = _anthropic_adapter()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    async def no_tools():
        return []
    with eb.scope(eb.run_budget()) as budget:
        result = await tool_loop.run_native(system="S", user_content="hi", history=[], emit=lambda e: None,
                                            on_chunk=lambda c: None, resolve_tools=no_tools,
                                            stream_without_tools=True, allow_escalation=False)
    assert result["final"] == "Hello" and budget.tokens == 12_500
