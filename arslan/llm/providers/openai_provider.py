"""OpenAI-compatible provider (works with OpenAI, DeepSeek, local vLLM, etc.)."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from arslan.llm.providers.base import BaseLLMProvider
from arslan.models import LLMResponse


class OpenAIProvider(BaseLLMProvider):
    """HTTP client for any OpenAI-compatible /chat/completions endpoint."""

    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def __init__(self, model: str, api_key: str = "", base_url: str = "") -> None:
        effective_base_url = base_url or self.DEFAULT_BASE_URL
        super().__init__(model=model, api_key=api_key, base_url=effective_base_url)

    # ------------------------------------------------------------------
    # BaseLLMProvider interface
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "openai"


    @staticmethod
    def _translate(content: Any) -> Any:
        """Neutral blocks → OpenAI parts. Plain strings pass through untouched:
        the overwhelming majority of calls are text-only and must not have
        their payload reshaped by a feature they do not use."""
        if not isinstance(content, list):
            return content
        out: list[dict[str, Any]] = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "image":
                out.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{b['mime_type']};base64,{b['data']}"
                    },
                })
            elif isinstance(b, dict) and b.get("type") == "text":
                out.append({"type": "text", "text": b.get("text", "")})
            else:
                out.append(b)
        return out

    def _payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
    ) -> dict[str, Any]:
        """The ONE place this provider's body is built. chat() and chat_stream()
        both go through here so an image can never survive one path and be lost
        on the other."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {**m, "content": self._translate(m.get("content"))} for m in messages
            ],
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
        return payload

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """POST to {base_url}/chat/completions and return a normalised LLMResponse."""
        payload = self._payload(messages, tools, temperature)

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
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
        """Stream content deltas from an OpenAI-compatible SSE endpoint.

        Yields text content deltas only. Tool-call deltas (delta.tool_calls)
        are NOT surfaced on this path; callers needing tool calls should use
        the non-streaming chat() instead.

        S3-M3: requests the trailing usage frame via stream_options.include_usage
        and stashes it on self._last_stream_usage (read by LLMAdapter after the
        loop). Servers that never send the frame simply leave it None.
        """
        payload = self._payload(messages, tools, temperature)
        payload["stream"] = True
        # Ask for the trailing usage frame (a data frame with empty choices
        # and a usage object, sent just before [DONE]).
        payload["stream_options"] = {"include_usage": True}

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        yielded = False
        try:
            async for piece in self._stream_once(payload, headers):
                yielded = True
                yield piece
            return
        except httpx.HTTPStatusError as exc:
            # Some OpenAI-compatible servers (older vLLM/llama.cpp builds, strict
            # proxies) reject unknown params with a 4xx instead of ignoring them.
            # No retry helper exists in this file, so: minimal fallback — if the
            # request failed before any content arrived, retry exactly ONCE
            # without stream_options so chat never breaks over a nice-to-have.
            # A genuine 4xx (bad model, bad auth) fails identically on the retry
            # and still surfaces to the caller. Re-POSTing is billing-safe: a
            # request the server rejected with a 4xx never started generation
            # and is not billed.
            if yielded or not 400 <= exc.response.status_code < 500:
                raise
        payload.pop("stream_options", None)
        async for piece in self._stream_once(payload, headers):
            yield piece

    async def _stream_once(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> AsyncIterator[str]:
        """Single SSE request: yield content deltas, capture the usage frame."""
        self._last_stream_usage = None  # reset per attempt — no stale carry-over
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=60.0,
            ) as response:
                response.raise_for_status()
                async for raw_line in response.aiter_lines():
                    line = raw_line.lstrip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    # Trailing usage frame: choices is empty, usage is an object.
                    # (With include_usage, OpenAI sends "usage": null on content
                    # frames — hence the isinstance check, not a truthiness one.)
                    usage = obj.get("usage")
                    if isinstance(usage, dict):
                        tin = usage.get("prompt_tokens")
                        tout = usage.get("completion_tokens")
                        if tin is not None or tout is not None:
                            self._last_stream_usage = {"tokens_in": tin, "tokens_out": tout}
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        """Convert a raw OpenAI-format response dict to LLMResponse."""
        choice = data["choices"][0]
        message = choice["message"]

        content: str | None = message.get("content")

        # Extract tool calls if present
        tool_calls: list[dict[str, Any]] = []
        raw_tool_calls = message.get("tool_calls") or []
        for tc in raw_tool_calls:
            function = tc.get("function", {})
            arguments = function.get("arguments", "{}")
            # arguments may be a JSON string — try to parse it
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    pass  # leave as raw string if unparseable
            tool_calls.append(
                {
                    "id": tc.get("id", ""),
                    "type": tc.get("type", "function"),
                    "function": {
                        "name": function.get("name", ""),
                        "arguments": arguments,
                    },
                }
            )

        usage: dict[str, Any] = data.get("usage", {})

        return LLMResponse(
            role=message.get("role", "assistant"),
            content=content,
            tool_calls=tool_calls,
            usage=usage,
        )
