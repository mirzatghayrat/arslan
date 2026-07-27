"""Native Google Gemini provider — generateContent API (not OpenAI-compatible).

Differences handled: messages are ``contents`` with ``parts`` (role "model" for
the assistant), the system prompt is ``systemInstruction`` (top-level), auth is
the ``x-goog-api-key`` header, ``temperature`` lives under ``generationConfig``,
and streaming uses ``:streamGenerateContent?alt=sse``. Tools are driven by
Arslan's own prompt/JSON protocol, so native tool mapping is omitted.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from arslan.llm.providers.base import BaseLLMProvider
from arslan.models import LLMResponse



def _parts(content: Any) -> list[dict[str, Any]]:
    """Neutral blocks → Gemini parts.

    🔴 This replaces `[{"text": str(content)}]`, which was the single most
    dangerous line in the transport layer: given a block list it emitted the
    Python repr of that list — base64 and all — as TEXT. It never raised, the
    API answered, and the answer was computed from the literal characters of
    the blob. A silent wrong answer, not an error."""
    if not isinstance(content, list):
        return [{"text": str(content)}]
    parts: list[dict[str, Any]] = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "image":
            parts.append({"inline_data": {"mime_type": b["mime_type"], "data": b["data"]}})
        elif isinstance(b, dict) and b.get("type") == "text":
            parts.append({"text": b.get("text", "")})
        else:
            parts.append({"text": str(b)})
    return parts

class GeminiProvider(BaseLLMProvider):
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

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
        return "gemini"

    def _client(self) -> httpx.AsyncClient:
        if self._transport is not None:
            return httpx.AsyncClient(transport=self._transport)
        return httpx.AsyncClient()

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["x-goog-api-key"] = self.api_key
        return headers

    @staticmethod
    def _to_contents(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        """Split system text out and map the rest to Gemini ``contents``."""
        system = "\n\n".join(
            str(m.get("content", "")) for m in messages if m.get("role") == "system"
        )
        contents = []
        for m in messages:
            if m.get("role") == "system":
                continue
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": _parts(m["content"])})
        return system, contents

    def _payload(self, messages: list[dict[str, Any]], temperature: float) -> dict[str, Any]:
        system, contents = self._to_contents(messages)
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        return payload

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        url = f"{self.base_url}/models/{self.model}:generateContent"
        # Use a generous read timeout — Gemini thinking models (e.g. 2.5 Pro) can
        # hold the connection for 120 s+ before returning the first token.
        timeout = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0)
        async with self._client() as client:
            response = await client.post(
                url, json=self._payload(messages, temperature),
                headers=self._headers(), timeout=timeout,
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
        url = f"{self.base_url}/models/{self.model}:streamGenerateContent?alt=sse"
        # For streaming, the connect timeout is short but the read timeout must be
        # long enough for thinking models.  Each individual chunk arrives within a
        # few seconds once the model starts, so 30 s per-chunk is ample; the overall
        # wall-clock is bounded by the model's thinking budget, not by our timeout.
        timeout = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0)
        # S3-M3: the final SSE chunk carries usageMetadata with the complete
        # (cumulative) token counts — overwrite per field so the tail wins.
        # usageMetadata also has totalTokenCount; deliberately unused — pricing
        # needs the in/out split, and a total without the split is uncheckable.
        self._last_stream_usage = None
        tin: int | None = None
        tout: int | None = None
        async with self._client() as client:
            async with client.stream(
                "POST", url, json=self._payload(messages, temperature),
                headers=self._headers(), timeout=timeout,
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
                    meta = obj.get("usageMetadata")
                    if isinstance(meta, dict):
                        if meta.get("promptTokenCount") is not None:
                            tin = int(meta["promptTokenCount"])
                        if meta.get("candidatesTokenCount") is not None:
                            tout = int(meta["candidatesTokenCount"])
                        if tin is not None or tout is not None:
                            self._last_stream_usage = {"tokens_in": tin, "tokens_out": tout}
                    text = _first_text(obj)
                    if text:
                        yield text

    @staticmethod
    def _parse_response(data: dict[str, Any]) -> LLMResponse:
        text = _first_text(data)
        return LLMResponse(
            role="assistant",
            content=text or None,
            tool_calls=[],
            usage=data.get("usageMetadata", {}) or {},
        )


def _first_text(obj: dict[str, Any]) -> str:
    """Join the text parts of the first candidate in a Gemini response chunk."""
    candidates = obj.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts)
