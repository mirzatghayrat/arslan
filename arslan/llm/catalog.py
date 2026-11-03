"""Operator-maintained model catalog: providers -> seed models.

The static model list behind the provider and model dropdowns when a provider's live list can't be read.
Updated on release; NOT fetched remotely. (v0.1.64 ROUTE1: the capability scores and language map that fed task
routing, the suggest-primary helper and the capability table are gone with them.)
"""
from __future__ import annotations

# Keys MUST align with presets.PRESETS + presets.NATIVE.
# Model ids verified against official provider docs on 2026-07-11 (spec
# 2026-07-11-provider-catalog-local-models-design.md Part A2). Ids with an
# announced shutdown date or from a retired generation are deny-listed in
# tests/llm/test_catalog_freshness.py — extend that list when refreshing here.
CATALOG: dict[str, dict] = {
    "openai": {
        "models": ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"],
    },
    "deepseek": {
        "models": ["deepseek-v4-pro", "deepseek-v4-flash"],
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
        "models": ["claude-fable-5", "claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"],
    },
    "gemini": {
        "models": ["gemini-3.5-flash", "gemini-2.5-pro", "gemini-2.5-flash"],
    },
}


def models_for(provider: str) -> list[str]:
    entry = CATALOG.get(provider)
    return list(entry["models"]) if entry else []

