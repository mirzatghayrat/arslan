"""Tests for LLMAdapter — profile loading and provider creation."""
from __future__ import annotations

import pytest

from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers.openai_provider import OpenAIProvider
from arslan.models import CapabilityProfile


# ---------------------------------------------------------------------------
# load_profile — known models
# ---------------------------------------------------------------------------


def test_load_profile_gpt4o_returns_correct_profile():
    """load_profile('gpt-4o') loads values from gpt-4o.yaml."""
    adapter = LLMAdapter("openai", "gpt-4o", api_key="sk-test")
    profile = adapter.load_profile("gpt-4o")

    assert isinstance(profile, CapabilityProfile)
    assert profile.name == "gpt-4o"
    assert profile.provider == "openai"
    assert profile.reasoning == 5
    assert profile.tool_use == 5
    assert profile.chinese == 4
    assert profile.creative == 4
    assert profile.instruction == 5
    assert profile.max_context == 128000
    assert profile.cost_per_1k_tokens == pytest.approx(0.005)


def test_load_profile_claude_opus():
    """load_profile('claude-opus') loads the correct provider and reasoning score."""
    adapter = LLMAdapter("openai", "any-model")
    profile = adapter.load_profile("claude-opus")

    assert profile.provider == "anthropic"
    assert profile.reasoning == 5
    assert profile.max_context == 200000


def test_load_profile_deepseek_v3():
    """load_profile('deepseek-v3') returns Chinese score of 5."""
    adapter = LLMAdapter("openai", "any-model")
    profile = adapter.load_profile("deepseek-v3")

    assert profile.chinese == 5
    assert profile.cost_per_1k_tokens == pytest.approx(0.001)


def test_load_profile_llama_3_70b():
    """load_profile('llama-3-70b') returns zero cost and provider ollama."""
    adapter = LLMAdapter("openai", "any-model")
    profile = adapter.load_profile("llama-3-70b")

    assert profile.provider == "ollama"
    assert profile.cost_per_1k_tokens == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# load_profile — unknown model fallback
# ---------------------------------------------------------------------------


def test_load_profile_unknown_model_returns_default():
    """load_profile for an unknown model falls back to all-3 defaults."""
    adapter = LLMAdapter("openai", "unknown-model-xyz")
    profile = adapter.load_profile("unknown-model-xyz")

    assert isinstance(profile, CapabilityProfile)
    assert profile.name == "unknown-model-xyz"
    assert profile.reasoning == 3
    assert profile.tool_use == 3
    assert profile.chinese == 3
    assert profile.creative == 3
    assert profile.instruction == 3
    assert profile.max_context == 8000
    assert profile.cost_per_1k_tokens == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Adapter creation
# ---------------------------------------------------------------------------


def test_create_adapter_openai_provider():
    """LLMAdapter with provider_name='openai' creates an OpenAIProvider internally."""
    adapter = LLMAdapter("openai", "gpt-4o", api_key="sk-test")
    assert isinstance(adapter._provider, OpenAIProvider)
    assert adapter._provider.model == "gpt-4o"
    assert adapter._provider.api_key == "sk-test"


def test_create_adapter_with_custom_base_url():
    """LLMAdapter passes custom base_url through to the provider."""
    deepseek_url = "https://api.deepseek.com/v1"
    adapter = LLMAdapter(
        "openai",
        "deepseek-chat",
        api_key="ds-key",
        base_url=deepseek_url,
    )
    assert adapter._provider.base_url == deepseek_url


def test_create_adapter_unknown_provider_falls_back_to_openai():
    """Unknown provider_name gracefully falls back to OpenAIProvider."""
    adapter = LLMAdapter("ollama", "llama3", base_url="http://localhost:11434/v1")
    assert isinstance(adapter._provider, OpenAIProvider)
    assert adapter._provider.base_url == "http://localhost:11434/v1"
