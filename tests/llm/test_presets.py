"""Tests for OpenAI-compatible provider presets (Tier 0)."""
import pytest

from arslan.llm.presets import (
    PRESETS,
    expand_preset,
    list_presets,
    provider_options,
    resolve_preset,
)


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
    assert isinstance(p["default_model"], str)
    if name != "ollama":  # B5: ollama ships no seed default — dynamic list is king
        assert p["default_model"]
    assert p.get("label")


def test_ollama_seed_is_fully_dynamic():
    """Provider spec B5: ollama has no static default model and no seed model list —
    the dynamic catalog (/api/tags) is the only source; the UI shows "not detected"
    when no daemon answers."""
    from arslan.llm.catalog import models_for

    assert PRESETS["ollama"]["default_model"] == ""
    assert models_for("ollama") == []


# ---- provider_options: the unified dropdown list (presets + native) -------


def test_provider_options_includes_presets_and_native():
    keys = {o["key"] for o in provider_options()}
    # every Tier-0 preset is offered
    assert set(list_presets()) <= keys
    # native (non-OpenAI-compatible) providers are offered too
    assert {"anthropic", "gemini"} <= keys


def test_provider_options_have_required_display_fields():
    for o in provider_options():
        assert o["key"]
        assert o["label"]
        # every option carries a model default the UI can prefill — except ollama
        # (B5: no static seed; the dynamic list is the only source)
        assert isinstance(o["default_model"], str)
        if o["key"] != "ollama":
            assert o["default_model"]
        assert "base_url" in o  # native entries may be "" (SDK default)
        assert isinstance(o["native"], bool)


def test_native_options_have_no_base_url():
    by_key = {o["key"]: o for o in provider_options()}
    assert by_key["anthropic"]["native"] is True
    assert by_key["anthropic"]["base_url"] == ""
    assert by_key["gemini"]["native"] is True


def test_provider_options_has_no_duplicate_keys():
    keys = [o["key"] for o in provider_options()]
    assert len(keys) == len(set(keys))


# ---- expand_preset: turn a stored provider name into a real adapter config -


def test_expand_preset_fills_base_url_and_model_for_preset():
    provider, model, base_url = expand_preset("deepseek", "", "")
    assert provider == "openai"  # routed through the OpenAI-compatible client
    assert base_url.startswith("https://api.deepseek.com")
    assert model == PRESETS["deepseek"]["default_model"]


def test_expand_preset_respects_user_overrides():
    provider, model, base_url = expand_preset(
        "deepseek", "deepseek-reasoner", "https://proxy.example/v1"
    )
    assert provider == "openai"
    assert model == "deepseek-reasoner"  # user model kept
    assert base_url == "https://proxy.example/v1"  # user base_url kept


def test_expand_preset_passes_native_through_unchanged():
    assert expand_preset("anthropic", "claude-opus-4-8", "") == (
        "anthropic",
        "claude-opus-4-8",
        "",
    )


def test_expand_preset_unknown_provider_passes_through():
    assert expand_preset("mystery", "m1", "https://x/v1") == (
        "mystery",
        "m1",
        "https://x/v1",
    )
