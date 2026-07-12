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

from arslan.llm.cached_system import CachedSystem
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
    def _split_system(
        messages: list[dict[str, Any]],
    ) -> tuple[str | list[dict[str, Any]], list[dict[str, Any]]]:
        """Pull the system out of an OpenAI-style message list.

        Returns the ``system`` field for the Anthropic payload plus the non-system convo.
        The system is a plain **string** as before UNLESS a ``CachedSystem`` is present
        (the prompt-cache reorder, spec 2026-07-13) — then it becomes a **content-block
        array** with a single ``cache_control: ephemeral`` breakpoint on the byte-stable
        prefix block, and everything after it in an un-cached trailing block. Anthropic
        renders adjacent text blocks with no separator, so ``"".join(block texts)`` is
        byte-identical to the plain-string form — the model sees the same prompt either
        way; only the cache boundary is added.

        Floor degrade (spec R4): a ``cache_control`` breakpoint on a prefix shorter than
        the model's minimum-cacheable floor is simply not honored by Anthropic — it does
        NOT error, the block just isn't cached (``cache_creation_input_tokens == 0``). So
        no per-model gating is needed here; the breakpoint is always emitted and degrades
        naturally. Which Anthropic models actually cache the ~static prefix depends on
        those floors, which differ between the spec and the current platform docs — see
        the note in ``_payload``.
        """
        system_contents = [m.get("content", "") for m in messages if m.get("role") == "system"]
        convo = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") != "system"
        ]
        # Byte-exact full system text (unchanged behavior when no CachedSystem is present).
        full = "\n\n".join(str(m) for m in system_contents)
        cached = next((m for m in system_contents if isinstance(m, CachedSystem)), None)
        if cached is None or not cached.stable or not full.startswith(cached.stable):
            # No split (or an unexpected shape) → plain string, exactly as before.
            return full, convo
        stable = cached.stable
        trailing = full[len(stable):]  # = volatile (+ any other system msgs), byte-exact
        blocks: list[dict[str, Any]] = [
            {"type": "text", "text": stable, "cache_control": {"type": "ephemeral"}}
        ]
        if trailing:
            blocks.append({"type": "text", "text": trailing})
        return blocks, convo

    def _payload(self, messages: list[dict[str, Any]], temperature: float) -> dict[str, Any]:
        # D4/R4 — cache_control floors (which models actually benefit from the breakpoint):
        # a prefix below the model's minimum-cacheable floor is silently NOT cached (no
        # error, cache_creation_input_tokens == 0), so we never gate/branch on the model —
        # the breakpoint is always emitted and degrades naturally.
        #   Spec-cited floors (source platform.claude.com prompt-caching): Fable 5 = 512,
        #   Opus 4.8 = 1024, Sonnet 5 = 1024, Haiku 4.5 = 4096. Under those, Arslan's static
        #   answer prefix (~1280 tok) → Fable 5 / Opus 4.8 / Sonnet 5 cache; Haiku 4.5 does not.
        #   NOTE: the current claude-api reference tables list HIGHER floors (Opus 4.8 = 4096,
        #   Fable 5 / Sonnet 4.6 = 2048, Sonnet 4.5 = 1024) — under those, a ~1280-tok prefix
        #   would not reach any current-model floor. Either way the code is correct: it emits
        #   the breakpoint and lets Anthropic honor it iff the prefix clears that model's floor.
        # Tools: Arslan's Anthropic path is intentionally text-in/text-out (native tool-use
        # is not implemented — see the module docstring), so `tools` are not serialized into
        # this payload; D3's "cache_control on the last tool" therefore does not apply here.
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
        # S3-M3: real usage from the SSE events — input_tokens arrives on
        # message_start (nested under "message"), output_tokens on message_delta.
        # Review I2: message_start ALSO carries an initial output_tokens (≈1), so
        # publishing there would let a stream aborted mid-generation reach the
        # adapter with both fields non-None and be reported REAL with output
        # undercounted. message_start's numbers therefore stay in LOCALS;
        # self._last_stream_usage is published ONLY at message_delta, whose usage
        # confirms the message actually completed.
        self._last_stream_usage = None
        tin: int | None = None
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
                    etype = obj.get("type")
                    if etype == "content_block_delta":
                        delta = obj.get("delta") or {}
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            yield delta["text"]
                    elif etype == "message_start":
                        usage = (obj.get("message") or {}).get("usage") or {}
                        if usage.get("input_tokens") is not None:
                            tin = int(usage["input_tokens"])
                    elif etype == "message_delta":
                        # message_delta usage is CUMULATIVE per the API docs, so
                        # last-wins assignment (not summation) is the correct read.
                        usage = obj.get("usage") or {}
                        if usage.get("output_tokens") is not None:
                            self._last_stream_usage = {
                                "tokens_in": tin,
                                "tokens_out": int(usage["output_tokens"]),
                            }

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
