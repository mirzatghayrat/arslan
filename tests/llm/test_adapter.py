"""Tests for LLMAdapter — provider creation."""
from __future__ import annotations

from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers.openai_provider import OpenAIProvider


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


def test_create_adapter_custom_provider_uses_openai_with_base_url():
    """P3: "custom" misses the registry → OpenAIProvider talking to the user's
    base_url. This registry-miss fallback IS the custom provider's runtime
    chain — pin it."""
    adapter = LLMAdapter("custom", "m", base_url="http://x/v1")
    assert isinstance(adapter._provider, OpenAIProvider)
    assert adapter._provider.base_url == "http://x/v1"
    assert adapter._provider.model == "m"
