"""Tests for BaseLLMProvider and OpenAIProvider."""
from __future__ import annotations

import pytest

from arslan.llm.providers.base import BaseLLMProvider
from arslan.llm.providers.openai_provider import OpenAIProvider
from arslan.models import LLMResponse


# ---------------------------------------------------------------------------
# BaseLLMProvider — abstract class behaviour
# ---------------------------------------------------------------------------


def test_base_provider_cannot_be_instantiated():
    """Instantiating BaseLLMProvider directly must raise TypeError."""
    with pytest.raises(TypeError):
        BaseLLMProvider(model="any-model")  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# OpenAIProvider — construction
# ---------------------------------------------------------------------------


def test_openai_provider_creation():
    """OpenAIProvider stores model and api_key correctly."""
    provider = OpenAIProvider(model="gpt-4o", api_key="sk-test-key")
    assert provider.model == "gpt-4o"
    assert provider.api_key == "sk-test-key"
    assert provider.base_url == OpenAIProvider.DEFAULT_BASE_URL


def test_openai_provider_creation_deepseek():
    """OpenAIProvider for DeepSeek uses a custom base_url."""
    deepseek_url = "https://api.deepseek.com/v1"
    provider = OpenAIProvider(
        model="deepseek-chat",
        api_key="ds-key",
        base_url=deepseek_url,
    )
    assert provider.model == "deepseek-chat"
    assert provider.base_url == deepseek_url


def test_openai_provider_default_base_url_when_empty():
    """Passing empty base_url falls back to DEFAULT_BASE_URL."""
    provider = OpenAIProvider(model="gpt-4o", base_url="")
    assert provider.base_url == OpenAIProvider.DEFAULT_BASE_URL


# ---------------------------------------------------------------------------
# build_messages
# ---------------------------------------------------------------------------


def test_build_messages_system_and_user():
    """build_messages with no history returns [system, user]."""
    provider = OpenAIProvider(model="gpt-4o")
    messages = provider.build_messages(system="You are helpful.", user="Hello!")
    assert messages == [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello!"},
    ]


def test_build_messages_with_history():
    """build_messages inserts history between system and user."""
    provider = OpenAIProvider(model="gpt-4o")
    history = [
        {"role": "user", "content": "Previous question"},
        {"role": "assistant", "content": "Previous answer"},
    ]
    messages = provider.build_messages(
        system="You are helpful.",
        user="Follow-up question",
        history=history,
    )
    assert messages[0] == {"role": "system", "content": "You are helpful."}
    assert messages[1] == {"role": "user", "content": "Previous question"}
    assert messages[2] == {"role": "assistant", "content": "Previous answer"}
    assert messages[3] == {"role": "user", "content": "Follow-up question"}
    assert len(messages) == 4


def test_build_messages_none_history():
    """build_messages with history=None behaves the same as no history."""
    provider = OpenAIProvider(model="gpt-4o")
    messages = provider.build_messages(system="Sys", user="User", history=None)
    assert len(messages) == 2


# ---------------------------------------------------------------------------
# provider_name
# ---------------------------------------------------------------------------


def test_openai_provider_name():
    """provider_name must return 'openai'."""
    provider = OpenAIProvider(model="gpt-4o")
    assert provider.provider_name == "openai"
