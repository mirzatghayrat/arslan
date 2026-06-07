"""Base abstract provider interface for all LLM backends."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from arslan.models import LLMResponse


class BaseLLMProvider(ABC):
    """Abstract base for every LLM provider integration."""

    def __init__(self, model: str, api_key: str = "", base_url: str = "") -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique short identifier for this provider (e.g. 'openai', 'anthropic')."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Send a chat request and return a normalised LLMResponse."""

    # ------------------------------------------------------------------
    # Concrete helpers
    # ------------------------------------------------------------------

    def build_messages(
        self,
        system: str,
        user: str,
        history: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Assemble [system_msg, *history, user_msg] in OpenAI message format."""
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user})
        return messages
