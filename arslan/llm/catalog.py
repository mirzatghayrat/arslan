"""Operator-maintained model catalog: providers -> seed models.

The static model list behind the provider and model dropdowns when a provider's live list can't be read.
Updated on release; NOT fetched remotely. (v0.1.64 ROUTE1: the capability scores and language map that fed task
routing, the suggest-primary helper and the capability table are gone with them.)
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


# Keys MUST align with presets.PRESETS + presets.NATIVE.
# Priced providers' model ids follow prices.py (official pricing pages, read 2026-10-20); the hand-kept seeds of
# the other providers were verified against official provider docs on 2026-07-11 (spec
# 2026-07-11-provider-catalog-local-models-design.md Part A2). Ids with an
# announced shutdown date or from a retired generation are deny-listed in
# tests/llm/test_catalog_freshness.py — extend that list when refreshing here.
CATALOG: dict[str, dict] = {
    "openai": {
        "models": _priced_seed("openai"),
    },
    "deepseek": {
        "models": _priced_seed("deepseek"),
    },
    "qwen": {
        "models": ["qwen3.7-max", "qwen3.7-plus", "qwen3.6-flash"],
    },
    "kimi": {
        "models": ["kimi-k2.6", "kimi-k2.5"],
    },
    "zhipu": {
        "models": ["glm-5.2", "glm-5-turbo", "glm-4.7-flash"],
    },
    "minimax": {
        # MiniMax ids are case-sensitive: "MiniMax-M3", not "minimax-m3".
        "models": ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.5"],
    },
    "groq": {
        "models": ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
    },
    "together": {
        "models": ["Qwen/Qwen3.7-Max", "meta-llama/Llama-3.3-70B-Instruct-Turbo", "openai/gpt-oss-20b"],
    },
    "mistral": {
        # Versioned ids: the docs don't state which snapshot the -latest aliases resolve to.
        "models": ["mistral-medium-2604", "mistral-large-2512", "mistral-small-2603"],
    },
    "openrouter": {
        "models": ["anthropic/claude-sonnet-5", "openai/gpt-5.6-terra", "deepseek/deepseek-v4-flash", "google/gemini-3.5-flash"],
    },
    "ollama": {
        # B5: no seed models — what is actually pulled locally is the only honest
        # list; the dynamic catalog service (Settings /models endpoint, /api/tags)
        # is king.
        "models": [],
    },
    "anthropic": {
        "models": _priced_seed("anthropic"),
    },
    "gemini": {
        "models": _priced_seed("gemini"),
    },
}


def models_for(provider: str) -> list[str]:
    entry = CATALOG.get(provider)
    return list(entry["models"]) if entry else []

