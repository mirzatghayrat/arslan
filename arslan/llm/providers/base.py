"""Base abstract provider interface for all LLM backends."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from arslan.models import LLMResponse


class BaseLLMProvider(ABC):
    """Abstract base for every LLM provider integration."""

    # S3-M3: real usage captured from the most recent chat_stream call, when the
    # backend emitted a usage frame: {"tokens_in": int|None, "tokens_out": int|None}.
    # None when the last stream carried no usage frame — LLMAdapter reads this after
    # its stream loop and falls back to its estimate. Providers reset it at the start
    # of every stream attempt. Safe as instance state because llm_factory builds a
    # fresh provider per adapter per call (no concurrent streams share an instance).
    _last_stream_usage: dict[str, int | None] | None = None

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
        user: str | list[dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Assemble [system_msg, *history, user_msg] in OpenAI message format.

        `user` is either a plain string (34 of the 36 call sites) or a list of
        NEUTRAL content blocks, which each provider translates into its own
        native shape in its payload builder:

            {"type": "text",  "text": "..."}
            {"type": "image", "mime_type": "image/png", "data": "<base64>"}

        The neutral shape exists so that no caller has to know which provider
        is configured, and so the translation lives in exactly one place per
        provider — a second translation site is how a payload silently loses
        its image on the streaming path only."""
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user})
        return messages

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Default streaming: call chat() once and yield the full content.

        Providers that support real token streaming override this.
        """
        response = await self.chat(messages, tools=tools, temperature=temperature)
        if response.content:
            yield response.content
