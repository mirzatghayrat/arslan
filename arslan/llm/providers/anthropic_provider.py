"""Native Anthropic (Claude) provider — the Messages API is not OpenAI-compatible.

Differences handled here: the system prompt is a TOP-LEVEL field (not a message),
``max_tokens`` is required, auth is ``x-api-key`` + ``anthropic-version``, the
response is a list of content blocks, and streaming uses ``content_block_delta``
events, and tool schemas travel as a top-level ``tools`` array whose entries carry
``input_schema`` (not OpenAI's nested function/parameters).

G1: native tool-use IS implemented here now. The docstring previously said Arslan
drove tools "via its own prompt/JSON protocol" and therefore did not need this —
that protocol is ``tool_loop.run()``, which has had zero production callers for
some time (only ``run_native`` is reachable). The disclosure outlived its reason,
which is worse than no disclosure: it reads as a considered trade-off rather than
a gap, so nobody rechecks it.

Tool RESULTS still go back as neutral text (``tool_loop._record_tool_result``),
so no ``tool_use`` block ever re-enters the wire history and Anthropic's
tool_use/tool_result pairing constraint never activates. That is what keeps this
cheap — do not start echoing native blocks back without pricing the round-trip.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from arslan.llm.providers import errors as provider_errors

from arslan.llm.cached_system import CachedSystem
from arslan.llm.providers.base import BaseLLMProvider
from arslan.models import LLMResponse



def _translate(content: Any) -> Any:
    """Neutral blocks → Anthropic content blocks. Plain strings pass through:
    text-only calls (the overwhelming majority) must keep their exact payload.

    Note the cost shape this creates, disclosed in the spec (T6): the cache
    breakpoint sits on the system prefix, so images ride AFTER it and are never
    cached — a tool loop re-sends and re-bills them on every step."""
    if not isinstance(content, list):
        return content
    out: list[dict[str, Any]] = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "image":
            out.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": b["mime_type"],
                    "data": b["data"],
                },
            })
        elif isinstance(b, dict) and b.get("type") == "text":
            out.append({"type": "text", "text": b.get("text", "")})
        else:
            out.append(b)
    return out

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
            {"role": m["role"], "content": _translate(m["content"])}
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

    @staticmethod
    def _translate_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        """Neutral (OpenAI-function) schemas -> Anthropic's `tools` shape.

        G1. The neutral shape comes from `_native_tool_schemas` (tool_loop.py:938):
        `{"type":"function","function":{"name","description","parameters"}}`.
        Anthropic flattens that and calls the schema `input_schema`.

        Returns None for an empty/absent list so the caller can omit the key
        entirely: sending `"tools": []` would be a payload change on every
        toolless request, and on this provider a payload change is a prompt-cache
        change (tools render BEFORE system, see _payload).
        """
        if not tools:
            return None
        out: list[dict[str, Any]] = []
        for t in tools:
            fn = t.get("function") or {}
            name = fn.get("name") or t.get("name")
            if not name:
                continue
            out.append({
                "name": name,
                "description": fn.get("description", t.get("description", "")),
                "input_schema": fn.get("parameters") or t.get("input_schema") or {},
            })
        return out or None

    def _payload(self, messages: list[dict[str, Any]], temperature: float,
                 tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        # D4/R4 — cache_control floors (which models actually benefit from the breakpoint):
        # a prefix below the model's minimum-cacheable floor is silently NOT cached (no
        # error, cache_creation_input_tokens == 0), so we never gate/branch on the model —
        # the breakpoint is always emitted and degrades naturally.
        #   Floors (live platform.claude.com/docs/en/build-with-claude/prompt-caching,
        #   re-fetched + three-way reconciled 2026-07-13): Fable 5 = 512, Opus 4.8 = 1024,
        #   Sonnet 5 = 1024, Haiku 4.5 = 4096 (Bedrock: Fable 5 = 1024). Arslan's static answer
        #   prefix (~1280 tok, byte-derived — confirm with a keyed count_tokens on the real
        #   assembled prefix before relying on the ~256-tok margin over 1024) → Fable 5 caches
        #   comfortably; Opus 4.8 / Sonnet 5 cache iff the keyed count clears 1024; Haiku 4.5
        #   does not. (The bundled claude-api reference table lists HIGHER, STALE floors for the
        #   Claude 5 family — do not trust it; the live doc above is authoritative.) The code is
        #   correct regardless of the exact number: it always emits the breakpoint and Anthropic
        #   honors it iff the prefix clears that model's floor (else a silent zero-side-effect no-op).
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
        # Order matters for the cache, not just for readability: Anthropic renders
        # tools -> system -> messages, and the breakpoint sits at the system
        # prefix, so anything unstable in `tools` invalidates everything after it.
        # The stability requirement is discharged upstream (resolve_tools orders
        # its rows) and asserted by test_tool_transport.
        translated = self._translate_tools(tools)
        if translated:
            payload["tools"] = translated
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
                json=self._payload(messages, temperature, tools),
                headers=self._headers(),
                timeout=60.0,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as _exc:
                # Carry the provider's OWN explanation, not just the status
                # line — see providers/errors.py for why this matters.
                raise httpx.HTTPStatusError(
                    provider_errors.with_body(_exc),
                    request=_exc.request, response=_exc.response) from None
            data = response.json()
        return self._parse_response(data)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        if tools:
            # Ruling ④B. `run_native` only ever calls `chat`, so nothing passes
            # tools here — and a signature that accepts them and drops them on the
            # floor is precisely the bug G1 exists to fix. Refusing keeps the
            # parameter honest until someone actually implements streaming
            # tool-use, rather than leaving a feature that looks usable.
            raise NotImplementedError(
                f"{type(self).__name__}.chat_stream does not support tools; "
                "use chat() for tool-calling turns")
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
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as _exc:
                    # Carry the provider's OWN explanation, not just the status
                    # line — see providers/errors.py for why this matters.
                    raise httpx.HTTPStatusError(
                        provider_errors.with_body(_exc),
                        request=_exc.request, response=_exc.response) from None
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
        # G1. `tool_use` blocks become the SAME normalised shape openai_provider
        # emits, because run_native reads tc["function"]["name"]/["arguments"] and
        # must not have to know which provider answered. `input` arrives already
        # decoded here (OpenAI sends a JSON string and that parser decodes it), so
        # arguments is a dict on both paths.
        tool_calls = [
            {"id": b.get("id", ""), "type": "function",
             "function": {"name": b.get("name", ""), "arguments": b.get("input") or {}}}
            for b in blocks if b.get("type") == "tool_use"
        ]
        return LLMResponse(
            role=data.get("role", "assistant"),
            content=text or None,
            tool_calls=tool_calls,
            usage=data.get("usage", {}) or {},
        )
