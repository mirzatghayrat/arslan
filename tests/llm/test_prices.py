import pytest

from arslan.llm import prices
from arslan.llm.prices import LOCAL_PRICES, PRICES, fmt_usd, usd


# --- prefix matching -------------------------------------------------------


def test_versioned_model_id_hits_its_prefix():
    # "gpt-5.6-terra-2026xx" must resolve via the gpt-5.6-terra prefix (2.5 / 15).
    assert usd("gpt-5.6-terra-2026xx", 1_000_000, 0) == pytest.approx(2.5)
    assert usd("gpt-5.6-terra-2026xx", 0, 1_000_000) == pytest.approx(15.0)


def test_longest_prefix_wins_over_shorter(monkeypatch):
    # If a shorter overlapping prefix existed, the longer (more specific) one wins.
    monkeypatch.setattr(
        prices,
        "PRICES",
        {"gpt-5.6": (1.0, 1.0), "gpt-5.6-terra": (2.5, 15.0)},
    )
    assert usd("gpt-5.6-terra-2026xx", 1_000_000, 1_000_000) == pytest.approx(17.5)
    # And the shorter prefix still serves ids that only it matches.
    assert usd("gpt-5.6-sol", 1_000_000, 1_000_000) == pytest.approx(2.0)


def test_exact_model_id_matches():
    # 1000 in @ $3/M + 500 out @ $15/M = 0.003 + 0.0075
    assert usd("claude-sonnet-5", 1000, 500) == pytest.approx(0.0105)


# --- honest None (never guess) ---------------------------------------------


def test_unknown_model_returns_none():
    assert usd("kimi-k2.6", 1000, 1000) is None  # real catalog model, no price entry
    assert usd("totally-made-up", 1000, 1000) is None


def test_none_model_returns_none():
    assert usd(None, 1000, 1000) is None


def test_none_tokens_return_none():
    assert usd("claude-sonnet-5", None, 1000) is None
    assert usd("claude-sonnet-5", 1000, None) is None
    assert usd("claude-sonnet-5", None, None) is None


# --- local models are free ONLY when actually served locally (review I1) ----
# The same ids exist as PAID hosted models on BYOK OpenAI-compat clouds
# (DashScope serves deepseek-r1): $0 is gated on provider == "ollama".


@pytest.mark.parametrize("tag", ["llama3.1", "qwen3.5", "gemma4", "deepseek-r1"])
def test_local_seed_tags_cost_zero_on_ollama(tag):
    assert usd(tag, 500_000, 500_000, provider="ollama") == 0.0


def test_local_tag_variant_costs_zero_on_ollama():
    assert usd("llama3.1:70b", 1_000_000, 1_000_000, provider="ollama") == 0.0


@pytest.mark.parametrize("provider", ["qwen", "openai", "deepseek", None])
def test_local_tag_on_hosted_or_unknown_provider_is_not_free(provider):
    # deepseek-r1 on a hosted provider (or with no provider info) is a PAID call
    # we have no price for → honest None, never $0.
    assert usd("deepseek-r1", 1_000_000, 1_000_000, provider=provider) is None


def test_cloud_prefix_on_ollama_is_priced_zero_not_cloud_rate():
    # A tag sharing a cloud prefix but served via the ollama protocol is a LOCAL
    # call — the protocol has no per-token billing, so $0, never the cloud rate.
    assert usd("claude-sonnet-5", 1000, 500, provider="ollama") == 0.0


def test_any_tag_on_ollama_is_zero():
    # M3 acceptance catch: the seed-tag allowlist left qwen2.5:0.5b unpriced —
    # provider-level $0 is the honest rule for the billing-free ollama protocol.
    assert usd("qwen2.5:0.5b", 2856, 2488, provider="ollama") == 0.0


def test_cloud_entries_unaffected_by_provider_arg():
    expected = pytest.approx(0.0105)
    assert usd("claude-sonnet-5", 1000, 500) == expected
    assert usd("claude-sonnet-5", 1000, 500, provider="anthropic") == expected
    assert usd("claude-sonnet-5", 1000, 500, provider="something-custom") == expected


# --- table hygiene ----------------------------------------------------------


def test_every_planned_entry_present():
    expected = {
        "claude-fable-5": (10.0, 50.0),
        "claude-opus-4-8": (5.0, 25.0),
        "claude-sonnet-5": (3.0, 15.0),
        "claude-haiku-4-5": (1.0, 5.0),
        "gpt-5.6-sol": (5.0, 30.0),
        "gpt-5.6-terra": (2.5, 15.0),
        "gpt-5.6-luna": (1.0, 6.0),
        "deepseek-v4-pro": (0.44, 0.87),
        "deepseek-v4-flash": (0.14, 0.28),
        "gemini-3.5-flash": (1.5, 9.0),
        "gemini-2.5-pro": (1.25, 10.0),
        "gemini-2.5-flash": (0.30, 2.50),
        "mistral-medium-2604": (2.0, 5.0),
        "mistral-large-2512": (0.5, 1.5),
        "mistral-small-2603": (0.15, 0.60),
        "qwen3.7-max": (2.5, 7.5),
        "qwen3.7-plus": (0.40, 1.20),
        "qwen3.6-flash": (0.05, 0.20),
    }
    for prefix, pair in expected.items():
        assert PRICES.get(prefix) == pair, f"PRICES[{prefix!r}] != {pair}"
    # Review I1: local $0 entries live in their OWN provider-gated table —
    # they must never leak into the provider-agnostic cloud table.
    expected_local = {
        "llama3.1": (0.0, 0.0),
        "qwen3.5": (0.0, 0.0),
        "gemma4": (0.0, 0.0),
        "deepseek-r1": (0.0, 0.0),
    }
    assert LOCAL_PRICES == expected_local
    assert not set(PRICES) & set(LOCAL_PRICES)


# --- fmt_usd ----------------------------------------------------------------


def test_fmt_none_passthrough():
    assert fmt_usd(None) is None


def test_fmt_true_zero_is_zero_not_less_than():
    # Local models really cost $0 — "<$0.0001" would dishonestly claim a cost.
    assert fmt_usd(0.0) == "$0.0000"


def test_fmt_below_display_threshold():
    assert fmt_usd(0.00005) == "<$0.0001"


def test_fmt_at_threshold_boundary():
    assert fmt_usd(0.0001) == "$0.0001"


def test_fmt_four_decimal_places():
    assert fmt_usd(0.0031) == "$0.0031"
    assert fmt_usd(0.0105) == "$0.0105"
    assert fmt_usd(12.34567) == "$12.3457"
