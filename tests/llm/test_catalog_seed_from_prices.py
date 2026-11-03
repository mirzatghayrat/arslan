"""v0.1.64 ROUTE1 change 6: the seed list of a provider prices.py prices comes from prices.py.

The seed had drifted (Anthropic still offered claude-opus-4-8, claude-sonnet-5 and claude-haiku-4-5 while
prices.py, read from the official pages on 2026-10-20, listed their successors). For the providers prices.py
prices, the seed is now the newest priced model of each family, so there is no second hand-kept list there.
Providers prices.py leaves unpriced by design (K4a: no official-page price, no row) keep a hand-kept seed.

These checks read prices.py on their own terms (family = the id without its version), so a seed that drifts
from it fails here whatever the catalog code does.
"""
import re

from arslan.llm import catalog
from arslan.llm.presets import NATIVE, PRESETS
from arslan.llm.prices import PRICES

PRICED_PROVIDERS = ("anthropic", "openai", "deepseek", "gemini")
_ID = {
    "anthropic": re.compile(r"claude-([a-z]+)-(\d+(?:-\d+)?)"),
    "openai": re.compile(r"gpt-(\d+\.\d+)-([a-z]+)"),
    "deepseek": re.compile(r"deepseek-v(\d+)-([a-z]+)"),
    "gemini": re.compile(r"gemini-(\d+\.\d+)-([a-z]+)"),
}
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


def _newest_priced(provider: str) -> dict[str, str]:
    newest: dict[str, tuple[tuple[int, ...], str]] = {}
    for model in PRICES:
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
