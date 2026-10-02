"""OpenAI-compatible provider (works with OpenAI, DeepSeek, local vLLM, etc.)."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from arslan.llm.providers import errors as provider_errors
from arslan.llm import request_evidence
from arslan.llm.locality import loopback_endpoint

from arslan.llm.providers.base import BaseLLMProvider
from arslan.models import LLMResponse


class OpenAIProvider(BaseLLMProvider):
    """HTTP client for any OpenAI-compatible /chat/completions endpoint."""

    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    #: Output budget declared on every request. NOT sending one is what caused
    #: the v0.1.25 field report: an aggregator (OpenRouter) reserves the MODEL's
    #: ceiling when the body is silent — 65536 for Claude — and refuses a key
    #: that could still afford 64381. Saying what we intend to use costs nothing
    #: and lets a nearly-spent budget keep working. Generous enough for long
    #: answers, far below any modern model's ceiling. 0.1.49: the opening
    #: budget is now per endpoint (output_budget.py); this stays the floor
    #: for unknown endpoints and aggregators that reserve credit.
    DEFAULT_MAX_TOKENS = 8192

    #: Assistant-message fields some compatible endpoints require back verbatim
    #: (DeepSeek/Kimi/GLM: reasoning_content; OpenRouter: reasoning,
    #: reasoning_details). Allow-list: only what the endpoint itself sent is ever
    #: echoed, so a strict endpoint never receives a field it did not produce.
    CONTINUATION_FIELDS = ("reasoning_content", "reasoning", "reasoning_details")

    def __init__(self, model: str, api_key: str = "", base_url: str = "",
                 max_tokens: int | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        effective_base_url = base_url or self.DEFAULT_BASE_URL
        super().__init__(model=model, api_key=api_key, base_url=effective_base_url)
        # 0.1.49 S5: per-endpoint opening budget and truncation ceiling
        # (arslan/llm/output_budget.py); an explicit max_tokens still wins.
        from arslan.llm.output_budget import for_endpoint
        budget = for_endpoint(effective_base_url, model)
        self.max_tokens = max_tokens or budget.initial
        self.output_ceiling = max(self.max_tokens, budget.ceiling)
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {"trust_env": not loopback_endpoint(self.base_url),
                                  "follow_redirects": False}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    def streams_tool_calls(self) -> bool:
        """Endpoints whose streamed tool calls are known to be complete. Others
        (older local servers often send partial tool-call deltas) stay
        non-streaming (0.1.49 S7)."""
        base = self.base_url.rstrip("/")
        return (base in {"https://api.deepseek.com", "https://api.deepseek.com/v1", "https://api.openai.com/v1"}
                or "openrouter.ai" in base)

    def supports_native_trajectory(self) -> bool:
        # The OpenAI chat-completions tool protocol is the compatible baseline.
        return True

    def build_trajectory_messages(self, system: Any, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Neutral trajectory (arslan/llm/trajectory.py) -> native wire messages.

        assistant: tool_calls with the server's exact argument text, plus the
        continuation fields it sent (reasoning_content ...) only when they came
        from this endpoint+model. tool: role "tool" bound by tool_call_id. A
        host-run result was never requested by the model, so it is not dressed
        up as a model call (no fabricated assistant turn): it is user context.
        Local bookkeeping keys ("_"-prefixed) never leave this function."""
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        endpoint = self.endpoint_fingerprint()
        for m in messages:
            role = m.get("role")
            if role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.get("content") or ""}
                calls = m.get("tool_calls") or []
                if calls:
                    msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                          "function": {"name": c["name"], "arguments": c["arguments_raw"]}}
                                         for c in calls]
                cont = m.get("_continuation") or {}
                if cont.get("protocol") == "openai" and cont.get("endpoint") == endpoint:
                    msg.update({k: v for k, v in (cont.get("fields") or {}).items()
                                if k in self.CONTINUATION_FIELDS})
                out.append(msg)
            elif role == "tool" and m.get("_synthetic"):
                out.append({"role": "user", "content":
                            f"Automatic pre-search (not requested by you) — RESULT for {m['name']}:\n{m['content']}"})
            elif role == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
            else:
                out.append({k: v for k, v in m.items() if not k.startswith("_")})
        return out

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
        tool_choice: str | None = None,
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
            "max_tokens": self.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice
        # Keep the configured model/endpoint. Only this task-local, tool-free
        # critique changes shape: thinking explicitly OFF on official DeepSeek
        # (the only endpoint where that switch is known), deterministic, short.
        # Never send a vendor-specific option to arbitrary compatible endpoints.
        from arslan.llm.request_policy import (
            CRITIQUE_MAX_OUTPUT_TOKENS, CRITIQUE_TEMPERATURE, bounded_critique)
        if bounded_critique.get() and not tools:
            payload["temperature"] = CRITIQUE_TEMPERATURE
            payload["max_tokens"] = min(self.max_tokens, CRITIQUE_MAX_OUTPUT_TOKENS)
            if self._official_deepseek():
                payload["thinking"] = {"type": "disabled"}
        return payload

    def _official_deepseek(self) -> bool:
        return (self.base_url.rstrip("/") in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}
                and self.model in {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-pro"})

    def supports_bounded_critique(self) -> bool:
        # Other OpenAI-compatible models may reason by default (o-series,
        # *-reasoner, hybrid thinking models) with no portable way to turn it off.
        return self._official_deepseek()

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        tool_choice: str | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        """POST to {base_url}/chat/completions and return a normalised LLMResponse.

        stream=True (native trajectory on streams_tool_calls() endpoints) reads
        the reply as SSE under an idle watchdog and assembles it; the caller
        still gets one complete response. A server that answers with plain JSON
        anyway is parsed as before."""
        payload = self._payload(messages, tools, temperature, tool_choice)
        if max_tokens:
            payload["max_tokens"] = max_tokens
        from arslan.execution_budget import model_request
        payload["max_tokens"] = model_request(payload["max_tokens"])
        from arslan.execution_checkpoint import save
        await save("before_model")
        evidence = await request_evidence.begin(payload)

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if stream:
            return await self._chat_streamed(payload, headers, evidence)
        async with self._client() as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                # A thinking model may legitimately take minutes before the
                # first byte of a non-streamed reply (0.1.49: larger budgets).
                timeout=httpx.Timeout(300.0, connect=15.0),
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as _exc:
                # Carry the provider's OWN explanation, not just the status
                # line — see providers/errors.py for why this matters.
                raise httpx.HTTPStatusError(
                    provider_errors.with_body(_exc),
                    request=_exc.request, response=_exc.response) from None
            await request_evidence.acknowledge(evidence)
            data = response.json()

        return self._parse_response(data)

    async def _chat_streamed(self, payload: dict[str, Any], headers: dict[str, str], evidence) -> LLMResponse:
        from arslan.llm import stream_assembly
        body = {**payload, "stream": True, "stream_options": {"include_usage": True}}
        async with self._client() as client:
            # The idle watchdog governs reads; httpx's own read timeout only
            # backs it up (keep-alive comments keep the socket busy anyway).
            async with client.stream("POST", f"{self.base_url}/chat/completions", json=body, headers=headers,
                                     timeout=httpx.Timeout(connect=15.0, read=stream_assembly.IDLE_S * 2,
                                                           write=60.0, pool=15.0)) as response:
                if response.status_code >= 400:
                    await response.aread()
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as _exc:
                    raise httpx.HTTPStatusError(
                        provider_errors.with_body(_exc),
                        request=_exc.request, response=_exc.response) from None
                await request_evidence.acknowledge(evidence)
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    await response.aread()
                    return self._parse_response(response.json())
                data = await stream_assembly.assemble(response)
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
        if tools:
            # Ruling ④B. `run_native` only ever calls `chat`, so nothing passes
            # tools here — and a signature that accepts them and drops them on the
            # floor is precisely the bug G1 exists to fix. Refusing keeps the
            # parameter honest until someone actually implements streaming
            # tool-use, rather than leaving a feature that looks usable.
            raise NotImplementedError(
                f"{type(self).__name__}.chat_stream does not support tools; "
                "use chat() for tool-calling turns")
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
        from arslan.execution_budget import model_request
        payload = {**payload, "max_tokens": model_request(payload["max_tokens"])}
        from arslan.execution_checkpoint import save
        await save("before_model")
        evidence = await request_evidence.begin(payload)
        async with self._client() as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
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
                await request_evidence.acknowledge(evidence)
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
            # The server's exact text: echoed back unchanged in native history,
            # and the only evidence of what a truncated call actually contained.
            arguments_raw = (arguments if isinstance(arguments, str)
                             else json.dumps(arguments, ensure_ascii=False))
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
                    "arguments_raw": arguments_raw,
                }
            )

        usage: dict[str, Any] = data.get("usage", {})
        fields = {k: message[k] for k in self.CONTINUATION_FIELDS
                  if message.get(k) is not None}
        finish = choice.get("finish_reason")

        return LLMResponse(
            role=message.get("role", "assistant"),
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=str(finish).lower() if finish else None,
            continuation=({"protocol": "openai", "endpoint": self.endpoint_fingerprint(),
                           "fields": fields} if fields else None),
        )
