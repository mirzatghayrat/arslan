"""Operator-maintained model catalog: providers -> models + capability scores.

Single source of truth for the provider dropdown, model dropdown, routing engine,
suggest-primary helper, and the read-only capability table. Updated on release; NOT
fetched remotely. Capability dimensions are language-NEUTRAL; language proficiency
lives in the per-provider `languages` map and is resolved at runtime via language_fit.
"""
from __future__ import annotations

import re

from arslan.llm.prices import PRICES

# v0.1.64 ROUTE1 change 6: for the providers prices.py prices, the seed is the newest priced model of each
# family, read from PRICES (families in PRICES order), so there is no second hand-kept list where prices.py has
# data. Providers prices.py leaves unpriced by design (K4a: no official-page price, no row) keep a hand-kept seed.
# A Claude minor is one or two digits and an eight-digit date is a snapshot, not a version (as
# providers/anthropic_provider.py reads Claude ids). The only row these patterns skip is DeepSeek's legacy
# "deepseek-flash" billing prefix; tests/llm/test_catalog_seed_from_prices.py fails on any other unread row.
_PRICED_ID = {
    "anthropic": re.compile(r"claude-(?P<family>[a-z]+)-(?P<version>\d+(?:-\d{1,2})?)(?:-\d{8})?"),
    "openai": re.compile(r"gpt-(?P<version>\d+(?:\.\d+)?)-(?P<family>[a-z]+)"),
    "deepseek": re.compile(r"deepseek-v(?P<version>\d+)-(?P<family>[a-z]+)"),
    "gemini": re.compile(r"gemini-(?P<version>\d+(?:\.\d+)?)-(?P<family>[a-z]+)"),
}
#: The unpriced ids a priced provider still seeds, ahead of its priced ones. ⓪Plan, 2026-11-03 (option b): only
#: Gemini's preset default, which presets.NATIVE keeps; prices.py: "gemini-3.5-flash has no price on the page
#: (it routes to gemini-3.6-flash)". Adding a second one is a decision, not a refresh.
UNPRICED_SEED_EXCEPTIONS: dict[str, tuple[str, ...]] = {"gemini": ("gemini-3.5-flash",)}


def _priced_seed(provider: str) -> list[str]:
    """The newest priced model of each of `provider`'s families, in PRICES order."""
    newest: dict[str, tuple[tuple[int, ...], str]] = {}
    for model in PRICES:
        m = _PRICED_ID[provider].fullmatch(model)
        if m is None:
            continue
        version = tuple(int(n) for n in re.split(r"[.-]", m["version"]))
        if m["family"] not in newest or version > newest[m["family"]][0]:
            newest[m["family"]] = (version, model)
    return [*UNPRICED_SEED_EXCEPTIONS.get(provider, ()), *(model for _, model in newest.values())]


# Universal, language-neutral dimensions (0..10).
CAPABILITY_DIMENSIONS = ("cost", "speed", "tool_calling", "reasoning", "long_context")

# Neutral language score when the user's language is unset/unknown.
DEFAULT_LANGUAGE_FIT = 6

# Maps the EXACT <option value="..."> strings from SettingsScreen.tsx → ISO codes.
# Also maps already-ISO codes to themselves for backward compatibility.
# Keys MUST stay in sync with the language <select> in web/src/components/SettingsScreen.tsx.
_LANGUAGE_DISPLAY_TO_ISO: dict[str, str] = {
    # Dropdown display strings (option value attributes)
    "English (US)": "en",
    "Chinese (Simplified)": "zh",
    "Japanese": "ja",
    "German": "de",
    # ISO pass-throughs (stored by older clients or set programmatically)
    "en": "en",
    "zh": "zh",
    "de": "de",
    "es": "es",
    "fr": "fr",
    "ja": "ja",
}


def normalize_language(value: str | None) -> str | None:
    """Map a raw Settings language value to an ISO-639-1 code.

    Handles both the UI dropdown display strings (e.g. "English (US)") and
    already-normalized ISO codes ("en").  Returns None for unknown / empty input
    so callers can fall back to DEFAULT_LANGUAGE_FIT.
    """
    if not value:
        return None
    return _LANGUAGE_DISPLAY_TO_ISO.get(value)


# Keys MUST align with presets.PRESETS + presets.NATIVE. Scores are curated defaults,
# refined on release. `cost` = cheapness (higher = cheaper).
# `languages` keys MUST cover all 6 UI locale ISO codes: en, zh, de, es, fr, ja.
# Priced providers' model ids follow prices.py (official pricing pages, read 2026-10-20); the hand-kept seeds of
# the other providers were verified against official provider docs on 2026-07-11 (spec
# 2026-07-11-provider-catalog-local-models-design.md Part A2). Ids with an
# announced shutdown date or from a retired generation are deny-listed in
# tests/llm/test_catalog_freshness.py — extend that list when refreshing here.
CATALOG: dict[str, dict] = {
    "openai": {
        "models": _priced_seed("openai"),
        "capabilities": {"cost": 4, "speed": 7, "tool_calling": 9, "reasoning": 9, "long_context": 8},
        "languages": {"en": 10, "zh": 7, "de": 8, "es": 8, "fr": 8, "ja": 7},
    },
    "deepseek": {
        "models": _priced_seed("deepseek"),
        "capabilities": {"cost": 9, "speed": 7, "tool_calling": 7, "reasoning": 8, "long_context": 8},
        "languages": {"en": 8, "zh": 9, "de": 6, "es": 6, "fr": 6, "ja": 6},
    },
    "qwen": {
        "models": ["qwen3.7-max", "qwen3.7-plus", "qwen3.6-flash"],
        "capabilities": {"cost": 8, "speed": 8, "tool_calling": 9, "reasoning": 7, "long_context": 7},
        "languages": {"en": 7, "zh": 9, "de": 5, "es": 6, "fr": 5, "ja": 6},
    },
    "kimi": {
        "models": ["kimi-k2.6", "kimi-k2.5"],
        "capabilities": {"cost": 7, "speed": 7, "tool_calling": 7, "reasoning": 7, "long_context": 9},
        "languages": {"en": 7, "zh": 9, "de": 5, "es": 5, "fr": 5, "ja": 5},
    },
    "zhipu": {
        "models": ["glm-5.2", "glm-5-turbo", "glm-4.7-flash"],
        "capabilities": {"cost": 8, "speed": 8, "tool_calling": 7, "reasoning": 7, "long_context": 7},
        "languages": {"en": 6, "zh": 9, "de": 4, "es": 5, "fr": 4, "ja": 5},
    },
    "minimax": {
        # MiniMax ids are case-sensitive: "MiniMax-M3", not "minimax-m3".
        "models": ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.5"],
        "capabilities": {"cost": 7, "speed": 7, "tool_calling": 6, "reasoning": 6, "long_context": 7},
        "languages": {"en": 6, "zh": 9, "de": 4, "es": 5, "fr": 4, "ja": 5},
    },
    "groq": {
        "models": ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        "capabilities": {"cost": 8, "speed": 10, "tool_calling": 7, "reasoning": 7, "long_context": 6},
        "languages": {"en": 9, "zh": 5, "de": 7, "es": 7, "fr": 7, "ja": 5},
    },
    "together": {
        "models": ["Qwen/Qwen3.7-Max", "meta-llama/Llama-3.3-70B-Instruct-Turbo", "openai/gpt-oss-20b"],
        "capabilities": {"cost": 8, "speed": 8, "tool_calling": 7, "reasoning": 7, "long_context": 7},
        "languages": {"en": 9, "zh": 6, "de": 7, "es": 7, "fr": 7, "ja": 6},
    },
    "mistral": {
        # Versioned ids: the docs don't state which snapshot the -latest aliases resolve to.
        "models": ["mistral-medium-2604", "mistral-large-2512", "mistral-small-2603"],
        "capabilities": {"cost": 6, "speed": 7, "tool_calling": 8, "reasoning": 8, "long_context": 7},
        "languages": {"en": 9, "zh": 6, "de": 8, "es": 8, "fr": 9, "ja": 6},
    },
    "openrouter": {
        "models": ["anthropic/claude-sonnet-5", "openai/gpt-5.6-terra", "deepseek/deepseek-v4-flash", "google/gemini-3.5-flash"],
        "capabilities": {"cost": 6, "speed": 7, "tool_calling": 8, "reasoning": 9, "long_context": 8},
        "languages": {"en": 9, "zh": 7, "de": 8, "es": 8, "fr": 8, "ja": 7},
    },
    "ollama": {
        # B5: no seed models — what is actually pulled locally is the only honest
        # list; the dynamic catalog service (Settings /models endpoint, /api/tags)
        # is king. Capabilities/languages stay for the routing engine.
        "models": [],
        "capabilities": {"cost": 10, "speed": 5, "tool_calling": 5, "reasoning": 6, "long_context": 5},
        "languages": {"en": 8, "zh": 6, "de": 6, "es": 6, "fr": 6, "ja": 5},
    },
    "anthropic": {
        "models": _priced_seed("anthropic"),
        "capabilities": {"cost": 3, "speed": 6, "tool_calling": 9, "reasoning": 10, "long_context": 9},
        "languages": {"en": 10, "zh": 8, "de": 8, "es": 8, "fr": 8, "ja": 7},
    },
    "gemini": {
        "models": _priced_seed("gemini"),
        "capabilities": {"cost": 7, "speed": 8, "tool_calling": 8, "reasoning": 9, "long_context": 10},
        "languages": {"en": 10, "zh": 7, "de": 8, "es": 8, "fr": 8, "ja": 7},
    },
}


def models_for(provider: str) -> list[str]:
    entry = CATALOG.get(provider)
    return list(entry["models"]) if entry else []


def capabilities_for(provider: str) -> dict[str, int]:
    entry = CATALOG.get(provider)
    if not entry:
        return {dim: 5 for dim in CAPABILITY_DIMENSIONS}
    return dict(entry["capabilities"])


def language_fit(provider: str, language: str | None) -> int:
    """Return the provider's language proficiency score (0-10).

    Accepts both the raw Settings value (display string like "English (US)") and
    already-normalized ISO codes ("en").  Unknown languages return DEFAULT_LANGUAGE_FIT.
    """
    entry = CATALOG.get(provider)
    if not entry or not language:
        return DEFAULT_LANGUAGE_FIT
    iso = normalize_language(language)
    if iso is None:
        return DEFAULT_LANGUAGE_FIT
    return entry["languages"].get(iso, DEFAULT_LANGUAGE_FIT)
