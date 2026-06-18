"""Native Anthropic (Claude) provider — the Messages API is not OpenAI-compatible.

Differences handled here: the system prompt is a TOP-LEVEL field (not a message),
``max_tokens`` is required, auth is ``x-api-key`` + ``anthropic-version``, the
response is a list of content blocks, and streaming uses ``content_block_delta``
events. Arslan drives tools via its own prompt/JSON protocol, so native tool-use
mapping is intentionally not implemented (text in -> text out + usage).
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from arslan.llm.providers.base import BaseLLMProvider
from arslan.models import LLMResponse


class AnthropicProvider(BaseLLMProvider):
    DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
    ANTHROPIC_VERSION = "2023-06-01"
    DEFAULT_MAX_TOKENS = 4096

    def __init__(
        self,
        model: str,
        api_key: str = "",
        base_url: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(model=model, api_key=api_key, base_url=base_url or self.DEFAULT_BASE_URL)
        self._transport = transport

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def _client(self) -> httpx.AsyncClient:
        if self._transport is not None:
            return httpx.AsyncClient(transport=self._transport)
        return httpx.AsyncClient()

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "anthropic-version": self.ANTHROPIC_VERSION,
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    @staticmethod
    def _split_system(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        """Pull the system text out of an OpenAI-style message list."""
        system = "\n\n".join(
            str(m.get("content", "")) for m in messages if m.get("role") == "system"
        )
        convo = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") != "system"
        ]
        return system, convo

    def _payload(self, messages: list[dict[str, Any]], temperature: float) -> dict[str, Any]:
        system, convo = self._split_system(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.DEFAULT_MAX_TOKENS,
            "messages": convo,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        return payload

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        async with self._client() as client:
            response = await client.post(
                f"{self.base_url}/messages",
                json=self._payload(messages, temperature),
                headers=self._headers(),
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
        return self._parse_response(data)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        payload = {**self._payload(messages, temperature), "stream": True}
        async with self._client() as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/messages",
                json=payload,
                headers=self._headers(),
                timeout=60.0,
            ) as response:
                response.raise_for_status()
                async for raw_line in response.aiter_lines():
                    line = raw_line.strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        obj = json.loads(line[len("data:") :].strip())
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") == "content_block_delta":
                        delta = obj.get("delta") or {}
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            yield delta["text"]

    @staticmethod
    def _parse_response(data: dict[str, Any]) -> LLMResponse:
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return LLMResponse(
            role=data.get("role", "assistant"),
            content=text or None,
            tool_calls=[],
            usage=data.get("usage", {}) or {},
        )
