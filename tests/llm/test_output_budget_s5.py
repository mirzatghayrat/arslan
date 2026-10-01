"""0.1.49 S5: output budgets per endpoint and budget weight per response."""
import pytest

from arslan.llm import output_budget, usage_weight
from arslan.llm.providers.openai_provider import OpenAIProvider


@pytest.mark.parametrize("base,model,expected", [
    ("https://api.deepseek.com", "deepseek-v4-flash", (32_768, 131_072)),
    ("https://api.deepseek.com/v1/", "deepseek-v4-pro", (32_768, 131_072)),
    ("https://openrouter.ai/api/v1", "deepseek/deepseek-v4", (8_192, 32_768)),
    ("http://127.0.0.1:11434/v1", "qwen3", (8_192, 16_384)),
    ("https://api.deepseek.com", "some-future-model", (8_192, 16_384)),
])
def test_budget_table(base, model, expected):
    b = output_budget.for_endpoint(base, model)
    assert (b.initial, b.ceiling) == expected


def test_provider_declares_the_endpoint_budget_unless_told_otherwise():
    assert OpenAIProvider(model="deepseek-v4-flash", base_url="https://api.deepseek.com").max_tokens == 32_768
    assert OpenAIProvider(model="x", base_url="https://openrouter.ai/api/v1").max_tokens == 8_192
    assert OpenAIProvider(model="deepseek-v4-flash", base_url="https://api.deepseek.com",
                          max_tokens=1000).max_tokens == 1000


def test_execution_budget_no_longer_caps_output_at_8192():
    from arslan.execution_budget import Limits
    assert Limits().output_tokens_per_request >= 131_072


def test_clamp_is_recorded_when_the_budget_grants_less_than_requested():
    from arslan.execution_budget import Budget, Limits
    budget = Budget(Limits(tokens=10_000))
    assert budget.model_request(32_768) == 10_000 and budget.last_output_clamped
    assert budget.model_request(500) == 500 and not budget.last_output_clamped


@pytest.mark.parametrize("usage,expected", [
    # DeepSeek: 9000 cached + 1000 uncached input, 500 out -> 1000 + 900 + 500
    ({"prompt_cache_hit_tokens": 9000, "prompt_cache_miss_tokens": 1000, "completion_tokens": 500,
      "prompt_tokens": 10000, "total_tokens": 10500}, 2400),
    ({"prompt_tokens": 10000, "completion_tokens": 500,
      "prompt_tokens_details": {"cached_tokens": 9000}}, 2400),                       # OpenAI
    ({"input_tokens": 1000, "cache_read_input_tokens": 9000, "cache_creation_input_tokens": 200,
      "output_tokens": 500}, 2600),                                                  # Anthropic
    ({"promptTokenCount": 10000, "cachedContentTokenCount": 9000, "candidatesTokenCount": 400,
      "thoughtsTokenCount": 100}, 2400),                                             # Gemini
    ({"prompt_tokens": 10000, "completion_tokens": 500, "total_tokens": 10500}, None),  # no breakdown
    ({}, None),
])
def test_charged_tokens(usage, expected):
    assert usage_weight.charged_tokens(usage) == expected


@pytest.mark.asyncio
async def test_adapter_debits_the_weighted_cost_and_reports_raw_usage():
    """End to end through LLMAdapter: the execution budget is debited the
    cache-weighted amount, the user's usage bucket still sees raw tokens, and
    the request declares the endpoint's opening budget."""
    import json

    import httpx

    from arslan.execution_budget import Budget, Limits, scope
    from arslan.llm import usage_sink
    from arslan.llm.adapter import LLMAdapter

    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"},
            "finish_reason": "stop"}], "usage": {"prompt_tokens": 10000, "completion_tokens": 500,
            "total_tokens": 10500, "prompt_cache_hit_tokens": 9000, "prompt_cache_miss_tokens": 1000}})
    base = "https://api.deepseek.com"
    adapter = LLMAdapter("openai", "deepseek-v4-flash", api_key="k", base_url=base)
    adapter._provider = OpenAIProvider(model="deepseek-v4-flash", api_key="k", base_url=base,
                                       transport=httpx.MockTransport(handler))
    with scope(Budget(Limits())) as budget, usage_sink.collecting() as bucket:
        await adapter.chat("S", "hi")
    assert budget.tokens == 2400
    assert sum(bucket) == 10500
    assert bodies[0]["max_tokens"] == 32_768


def test_adapter_max_tokens_override_pins_the_opening_budget():
    """Cost-capped evals pin the budget their approved spend math assumes."""
    from arslan.llm.adapter import LLMAdapter
    pinned = LLMAdapter("openai", "deepseek-v4-flash", base_url="https://api.deepseek.com", max_tokens=8192)
    assert pinned._provider.max_tokens == 8192
    assert LLMAdapter("openai", "deepseek-v4-flash", base_url="https://api.deepseek.com")._provider.max_tokens == 32_768
    with pytest.raises(ValueError):
        LLMAdapter("anthropic", "claude-x", max_tokens=8192)
