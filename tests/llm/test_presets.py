"""Tests for OpenAI-compatible provider presets (Tier 0)."""
import pytest

from arslan.llm.presets import PRESETS, list_presets, resolve_preset


def test_known_preset_resolves_with_base_url():
    p = resolve_preset("deepseek")
    assert p is not None
    assert p["provider"] == "openai"
    assert p["base_url"].startswith("https://api.deepseek.com")
    assert p["default_model"]


def test_unknown_preset_returns_none():
    assert resolve_preset("nope") is None


def test_resolve_is_case_insensitive():
    assert resolve_preset("DeepSeek") == resolve_preset("deepseek")


def test_list_presets_includes_chinese_and_local_and_aggregator():
    names = set(list_presets())
    # Chinese models (all OpenAI-compatible)
    assert {"deepseek", "qwen", "kimi", "zhipu"} <= names
    # local + aggregator
    assert "ollama" in names
    assert "openrouter" in names


@pytest.mark.parametrize("name", list(PRESETS))
def test_every_preset_is_well_formed(name):
    p = PRESETS[name]
    assert p["provider"] == "openai"  # all Tier-0 entries go through the OpenAI-compatible path
    assert p["base_url"].startswith(("http://", "https://"))
    assert isinstance(p["default_model"], str) and p["default_model"]
    assert p.get("label")
