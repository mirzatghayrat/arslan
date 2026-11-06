"""v0.1.64 ROUTE1 change 6: the seed list of a provider prices.py prices comes from prices.py.

The seed had drifted (Anthropic still offered claude-opus-4-8, claude-sonnet-5 and claude-haiku-4-5 while
prices.py, read from the official pages on 2026-10-20, listed their successors). For the providers prices.py
prices, the seed is now the newest priced model of each family, so there is no second hand-kept list there.
Providers prices.py leaves unpriced by design (K4a: no official-page price, no row) keep a hand-kept seed.

These checks read prices.py with their own patterns (family = the id without its version), and every
claude-/gpt-/deepseek-/gemini- row of PRICES must parse under them or be skipped by name. So a price row
neither these patterns nor the catalog's read (a new naming style such as "gpt-6-sol") fails here instead of
being left out of the seed unseen.
"""
import re

import pytest

from arslan.llm import catalog
from arslan.llm.presets import NATIVE, PRESETS
from arslan.llm.prices import PRICES

PRICED_PROVIDERS = ("anthropic", "openai", "deepseek", "gemini")
_PREFIX = {"anthropic": "claude-", "openai": "gpt-", "deepseek": "deepseek-", "gemini": "gemini-"}
# A minor is one or two digits and an eight-digit date is a snapshot, not a version (anthropic_provider.py
# reads Claude ids the same way): claude-sonnet-5-20260601 is Sonnet 5, not 5.20260601.
_ID = {
    "anthropic": re.compile(r"claude-([a-z]+)-(\d+(?:-\d{1,2})?)(?:-\d{8})?"),
    "openai": re.compile(r"gpt-(\d+(?:\.\d+)?)-([a-z]+)"),
    "deepseek": re.compile(r"deepseek-v(\d+)-([a-z]+)"),
    "gemini": re.compile(r"gemini-(\d+(?:\.\d+)?)-([a-z]+)"),
}
# PRICES rows that are prefixes for billing, not seed models. prices.py: "The legacy names deepseek-v4-flash
# ... are billed at the Flash price."
NOT_SEED_MODELS = {"deepseek-flash"}
# ⓪Plan, 2026-11-03 (option b): Gemini's preset default is the one unpriced id a priced provider seeds.
# prices.py: "gemini-3.5-flash has no price on the page (it routes to gemini-3.6-flash): unpriced."
NAMED_EXCEPTIONS = {("gemini", "gemini-3.5-flash")}


def _family_and_version(provider: str, model: str) -> tuple[str, tuple[int, ...]] | None:
    m = _ID[provider].fullmatch(model)
    if m is None:
        return None
    a, b = m.groups()
    family, version = (a, b) if provider == "anthropic" else (b, a)
    return family, tuple(int(n) for n in re.split(r"[.-]", version))


def _newest_priced(provider: str, prices=PRICES) -> dict[str, str]:
    newest: dict[str, tuple[tuple[int, ...], str]] = {}
    for model in prices:
        parsed = _family_and_version(provider, model)
        if parsed and (parsed[0] not in newest or parsed[1] > newest[parsed[0]][0]):
            newest[parsed[0]] = (parsed[1], model)
    return {family: model for family, (_, model) in newest.items()}


def _default(provider: str) -> str:
    return (PRESETS.get(provider) or NATIVE[provider])["default_model"]


def test_a_priced_provider_seeds_the_newest_priced_model_of_every_family_and_nothing_else():
    for provider in PRICED_PROVIDERS:
        newest = _newest_priced(provider)
        assert newest, f"{provider}: prices.py has no family this check can read"
        seeded = [m for m in catalog.models_for(provider) if (provider, m) not in NAMED_EXCEPTIONS]
        assert sorted(seeded) == sorted(newest.values()), provider


def test_every_priced_row_of_these_providers_is_read_or_skipped_by_name():
    unread = [m for p in PRICED_PROVIDERS for m in PRICES
              if m.startswith(_PREFIX[p]) and m not in NOT_SEED_MODELS and _family_and_version(p, m) is None]
    assert unread == []


@pytest.mark.parametrize(("provider", "added", "expected", "gone"), [
    ("openai", "gpt-6-sol", "gpt-6-sol", "gpt-5.6-sol"),                        # a version with no minor
    ("anthropic", "claude-sonnet-5-20260601", "claude-sonnet-5-5", None),      # a date is not a minor
])
def test_a_new_price_row_reaches_the_seed_by_version(monkeypatch, provider, added, expected, gone):
    prices = {**PRICES, added: (1.0, 1.0)}
    monkeypatch.setattr(catalog, "PRICES", prices)
    seed = catalog._priced_seed(provider)
    assert sorted(seed) == sorted(_newest_priced(provider, prices).values())
    assert expected in seed and (gone is None or gone not in seed)


def test_the_drifted_anthropic_seed_is_gone():
    seed = catalog.models_for("anthropic")
    assert {"claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"}.isdisjoint(seed)
    assert {"claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"} <= set(seed)


def test_every_seed_model_of_a_priced_provider_is_priced_except_the_named_one():
    unpriced = {(p, m) for p in PRICED_PROVIDERS for m in catalog.models_for(p) if m not in PRICES}
    assert unpriced == NAMED_EXCEPTIONS
    assert catalog.UNPRICED_SEED_EXCEPTIONS == {p: (m,) for p, m in NAMED_EXCEPTIONS}


def test_a_priced_providers_default_is_priced_except_the_named_one():
    unpriced = {(p, _default(p)) for p in PRICED_PROVIDERS if _default(p) not in PRICES}
    assert unpriced == NAMED_EXCEPTIONS


def test_anthropic_new_configs_start_on_sonnet_5_5():
    # ⓪Plan, 2026-11-03 (option b): same price as claude-sonnet-5, newer. Existing configs keep their model.
    assert _default("anthropic") == "claude-sonnet-5-5"


def test_unpriced_providers_keep_a_hand_kept_seed():
    for provider in set(catalog.CATALOG) - set(PRICED_PROVIDERS) - {"ollama"}:
        assert catalog.models_for(provider), provider
