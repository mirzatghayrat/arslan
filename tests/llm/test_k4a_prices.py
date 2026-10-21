"""K4a: a response is priced by cache tier — uncached input, cache read, cache write (5 minutes or 1
hour) and output, each at its own price. Before, only input and output were priced: DeepSeek's cache
hits at the full input price, Anthropic's cache reads and writes not at all.

The table here is patched, so these tests pin the pricing logic, not today's numbers.
"""
import json

import httpx
import pytest

from arslan.llm import prices, usage_sink


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setattr(prices, "PRICES", {"claude-x": (4.0, 20.0), "claude-long": (4.0, 20.0), "deepseek-x": (0.5, 1.0),
                                           "gpt-x": (2.0, 8.0), "gemini-x": (1.0, 6.0), "plain-x": (1.0, 2.0)})
    monkeypatch.setattr(prices, "CACHE_PRICES", {"claude-x": (0.4, 5.0, 8.0), "claude-long": (0.4, 5.0, 8.0),
                                                 "deepseek-x": (0.05, None, None),
                                                 "gpt-x": (0.5, None, None), "gemini-x": (0.25, None, None)})
    monkeypatch.setattr(prices, "LONG_PROMPT_PRICES", {"claude-long": (100_000, (8.0, 40.0), (0.8, 10.0, 16.0))})
    monkeypatch.setattr(prices, "OFF_PEAK_HALF", ())


M = 1_000_000


def test_anthropic_reads_and_each_kind_of_write_have_their_own_price(table):
    usage = {"input_tokens": M, "cache_read_input_tokens": 2 * M, "cache_creation_input_tokens": M,
             "cache_creation": {"ephemeral_5m_input_tokens": M // 2, "ephemeral_1h_input_tokens": M // 2},
             "output_tokens": M // 10}
    assert prices.usd_for_usage("claude-x-2026", usage) == pytest.approx(4 + 0.8 + 2.5 + 4.0 + 2.0)


@pytest.mark.parametrize("long_cache, write_price", [(True, 8.0), (False, 5.0)])
def test_writes_without_a_ttl_split_follow_the_cache_the_request_asked_for(table, long_cache, write_price):
    usage = {"input_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": M, "output_tokens": 0}
    assert prices.usd_for_usage("claude-x", usage, long_cache=long_cache) == pytest.approx(write_price)


def test_deepseek_hits_are_priced_as_hits_not_as_input(table):
    usage = {"prompt_tokens": 10 * M, "prompt_cache_hit_tokens": 9 * M, "prompt_cache_miss_tokens": M,
             "completion_tokens": M // 2}
    assert prices.usd_for_usage("deepseek-x", usage) == pytest.approx(0.5 + 0.45 + 0.5)
    assert prices.usd("deepseek-x", 10 * M, M // 2) == pytest.approx(5.5)          # the old, in/out-only figure


def test_openai_cached_input_and_gemini_cached_content_and_thoughts(table):
    openai = {"prompt_tokens": M, "completion_tokens": M // 10, "prompt_tokens_details": {"cached_tokens": 800_000}}
    assert prices.usd_for_usage("gpt-x", openai) == pytest.approx(0.4 + 0.4 + 0.8)
    gemini = {"promptTokenCount": M, "cachedContentTokenCount": M // 2, "candidatesTokenCount": M // 10,
              "thoughtsTokenCount": M // 10}
    assert prices.usd_for_usage("gemini-x", gemini) == pytest.approx(0.5 + 0.125 + 1.2)


def test_what_cannot_be_priced_honestly_is_none(table):
    assert prices.usd_for_usage("unknown-model", {"input_tokens": 1, "output_tokens": 1}) is None
    assert prices.usd_for_usage(None, {"input_tokens": 1, "output_tokens": 1}) is None
    assert prices.usd_for_usage("claude-x", {}) is None                            # no real usage: an estimate
    # cache tokens on a model whose cache price isn't confirmed: unknown, never priced as input
    assert prices.usd_for_usage("plain-x", {"input_tokens": 10, "cache_read_input_tokens": 10,
                                            "output_tokens": 1}) is None
    assert prices.usd_for_usage("plain-x", {"prompt_tokens": M, "completion_tokens": M}) == pytest.approx(3.0)
    assert prices.usd_for_usage("llama3.1", {"prompt_tokens": 5, "completion_tokens": 5}, provider="ollama") == 0.0


def test_every_row_of_a_provider_that_reports_its_cache_has_cache_prices():
    """Condition (a) of ⓪Plan's K4a answers: a row is in the table only with numbers confirmed on the
    provider's official page; for the providers that report cache tokens that includes the cache prices."""
    cached = ("claude-", "gpt-", "deepseek-", "gemini-")
    missing = [key for key in prices.PRICES if key.startswith(cached) and key not in prices.CACHE_PRICES]
    assert missing == []


def test_a_turn_costs_the_sum_of_its_responses_prices(table):
    from server.orchestrator.arslan import _frame_usd
    with usage_sink.collecting():
        usage_sink.report_detail(tokens_in=1000, tokens_out=10, model="claude-x", provider="anthropic", usd=0.25)
        usage_sink.report_detail(tokens_in=2000, tokens_out=20, model="claude-x", provider="anthropic", usd=0.5)
        assert _frame_usd(usage_sink.detail()["buckets"]) == pytest.approx(0.75)
        usage_sink.report_detail(tokens_in=10, tokens_out=1, model="unknown", provider="x", usd=None)
        assert _frame_usd(usage_sink.detail()["buckets"]) is None                  # one unpriced bucket: unknown


async def test_a_claude_response_reports_its_price_by_cache_tier(table):
    from arslan.llm.adapter import LLMAdapter
    from arslan.llm.providers.anthropic_provider import AnthropicProvider
    reply = {"role": "assistant", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Done."}],
             "usage": {"input_tokens": M, "cache_read_input_tokens": 2 * M, "cache_creation_input_tokens": 0,
                       "output_tokens": M // 10}}

    def handler(request):
        json.loads(request.content)
        return httpx.Response(200, json=reply)
    adapter = LLMAdapter("anthropic", "claude-x")
    adapter._provider = AnthropicProvider("claude-x", api_key="k", transport=httpx.MockTransport(handler))
    with usage_sink.collecting():
        await adapter.chat("S", "hi")
        [bucket] = usage_sink.detail()["buckets"]
    assert bucket["usd"] == pytest.approx(4 + 0.8 + 2.0)


def test_a_long_prompt_pays_the_long_prompt_prices_for_all_its_tokens(table):
    """Haiku 5.5 over 100k, gpt-5.6 over 272k, Gemini 2.5 Pro over 200k: the whole input counts, cache
    reads and writes included, and a request over the threshold pays the higher prices throughout."""
    short = {"input_tokens": 50_000, "cache_read_input_tokens": 50_000, "cache_creation_input_tokens": 0,
             "output_tokens": 1_000}                                              # 100k: not over
    long = {**short, "cache_read_input_tokens": 50_001}
    assert prices.usd_for_usage("claude-long", short) == pytest.approx(0.2 + 0.02 + 0.02)
    assert prices.usd_for_usage("claude-long", long) == pytest.approx(0.4 + 50_001 / M * 0.8 + 0.04)


def test_deepseek_off_peak_is_half_the_peak_price(table, monkeypatch):
    """DeepSeek's page: off-peak rates are half; peak is 01:00-04:00 and 06:00-10:00 UTC, Monday to Friday.
    (Chinese public holidays are off-peak all day; they aren't modelled, so they price at peak.)"""
    from datetime import datetime, timezone
    monkeypatch.setattr(prices, "OFF_PEAK_HALF", ("deepseek-",))
    usage = {"prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": M, "completion_tokens": 0}
    tuesday_peak = datetime(2026, 10, 20, 2, 30, tzinfo=timezone.utc)
    tuesday_off = datetime(2026, 10, 20, 5, 0, tzinfo=timezone.utc)
    saturday = datetime(2026, 10, 24, 2, 30, tzinfo=timezone.utc)
    assert prices.usd_for_usage("deepseek-x", usage, now=tuesday_peak) == pytest.approx(0.5)
    assert prices.usd_for_usage("deepseek-x", usage, now=tuesday_off) == pytest.approx(0.25)
    assert prices.usd_for_usage("deepseek-x", usage, now=saturday) == pytest.approx(0.25)


@pytest.mark.parametrize("model, row", [
    ("claude-opus-5-5", ((4.0, 20.0), (0.20, 5.0, 8.0))),
    ("claude-sonnet-5-5", ((2.0, 10.0), (0.10, 2.5, 4.0))),
    ("claude-sonnet-5", ((2.0, 10.0), (0.20, 2.5, 4.0))),
    ("claude-fable-5-1", ((10.0, 50.0), (0.25, 12.5, 20.0))),
    ("deepseek-v4-pro", ((1.32, 3.96), (0.044, None, None))),
    ("gpt-5.6-terra", ((2.0, 12.0), (0.20, None, None))),
    ("gemini-2.5-flash", ((0.30, 2.50), (0.03, None, None))),
])
def test_the_table_has_the_official_prices_read_on_2026_10_20(model, row):
    """Spot checks of the refreshed rows (official pages, read 2026-10-20; see prices.py)."""
    assert (prices._row(prices.PRICES, model), prices._row(prices.CACHE_PRICES, model)) == row


@pytest.mark.parametrize("model", ["gemini-3.5-flash", "deepseek-chat", "deepseek-reasoner",
                                   # ⓪Plan: unpriced until checked against their official pages
                                   "mistral-medium-2604", "mistral-large-2512", "mistral-small-2603",
                                   "qwen3.7-max", "qwen3.7-plus", "qwen3.6-flash"])
def test_a_model_the_official_page_does_not_price_is_unpriced(model):
    assert prices.usd_for_usage(model, {"prompt_tokens": 10, "completion_tokens": 10}) is None


def test_deepseek_bills_each_successful_search_from_its_start_date():
    """DeepSeek's pricing page (read 2026-10-21): Search and Fetch "$0.75" "Per 1,000 successful requests";
    "per-request billing starts at 00:00 Beijing time on November 1, 2026"."""
    from datetime import datetime, timezone
    before = datetime(2026, 10, 31, 15, 59, tzinfo=timezone.utc)                  # 23:59 Beijing, Oct 31
    after = datetime(2026, 10, 31, 16, 0, tzinfo=timezone.utc)                    # 00:00 Beijing, Nov 1
    assert prices.deepseek_search_usd(3, now=before) == 0.0
    assert prices.deepseek_search_usd(3, now=after) == pytest.approx(3 * 0.00075)


def test_a_native_search_counts_only_the_searches_that_returned_results():
    from server.registry.search_providers import successful_searches
    payload = {"content": [
        {"type": "web_search_tool_result", "content": [{"type": "web_search_result", "url": "https://a.test"}]},
        {"type": "web_search_tool_result", "content": {"type": "web_search_tool_result_error", "error_code": "x"}},
        {"type": "web_search_tool_result", "content": []},
        {"type": "text", "text": "done"}]}
    assert successful_searches(payload) == 2


def test_a_native_search_charges_its_searches_after_the_billing_date(monkeypatch):
    from arslan import execution_budget as eb
    from server.registry import search_providers
    usage = {"input_tokens": 1000, "output_tokens": 100}
    tokens = prices.usd_for_usage(search_providers.DeepSeekNativeProvider.MODEL, usage, provider="deepseek")
    monkeypatch.setattr(prices, "DEEPSEEK_SEARCH_BILLED_FROM", (2000, 1, 1, 0))       # billing has started
    budget = eb.run_budget()
    with eb.scope(budget):
        search_providers._account_usage(usage, searches=2)
    assert budget.usd == pytest.approx(tokens + 2 * 0.00075)
