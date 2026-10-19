"""Native Google Gemini provider — generateContent API (not OpenAI-compatible).

Differences handled: messages are ``contents`` with ``parts`` (role "model" for
the assistant), the system prompt is ``systemInstruction`` (top-level), auth is
the ``x-goog-api-key`` header, ``temperature`` lives under ``generationConfig``,
and streaming uses ``:streamGenerateContent?alt=sse``. Native function declarations
use the documented parametersJsonSchema field; functionCall responses normalize
to Arslan tools. Opaque continuation parts preserve Gemini thought signatures.
0.1.63 K1: the in-turn trajectory goes back natively (build_trajectory_messages);
function responses carry the result itself, not the old "TOOL RESULT for X" text.
The legacy text rendering (trajectory.to_legacy) stays as the ARSLAN_TOOL_PROTOCOL=legacy
rollback and the per-turn fallback after a protocol rejection; both go in v0.1.64, once
v0.1.63 has run 7 days with no protocol-class 400 from Gemini in M2 and M1 holds.
Streaming with tools remains explicitly unsupported; run_native uses chat().
"""
from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from arslan.llm.providers import errors as provider_errors
from arslan.llm import param_heal, request_evidence, tool_schema

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
        elif isinstance(b, dict) and b.get("type") == "provider_content":
            if b.get("provider") != "gemini":
                raise ValueError("foreign provider continuation cannot be sent to Gemini")
            parts.extend(b.get("parts") or [])
        elif isinstance(b, dict) and b.get("type") == "function_response":
            response = {"name": b["name"], "response": b["response"]}
            if b.get("id"):
                response["id"] = b["id"]
            parts.append({"functionResponse": response})
        else:
            parts.append({"text": str(b)})
    return parts

# 0.1.62 F3: a position in the one functionDeclarations list (Gemini's wording not checked).
_DECLARATION_INDEX = re.compile(r"function_?declarations\[(\d+)\]", re.I)


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

    def supports_native_trajectory(self) -> bool:
        return True              # 0.1.63 K1

    APPENDS_STATUS = True        # the step status is its own part after the results, kept (K1)

    def build_trajectory_messages(self, system: Any, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Neutral trajectory (arslan/llm/trajectory.py) -> Gemini turns (0.1.63 K1).

        A model turn that called functions is replayed as its own parts (thought signatures
        included). Each result answers its call with a functionResponse whose `response` is the
        result itself: the JSON object a tool returned, or {"output": text} for anything else
        (an untrusted result keeps its data frame). Screenshots, host-run results and the step's
        status follow as their own parts in the same user turn; same-role turns merge."""
        calls: dict[str, dict] = {}
        turns: list[tuple[str, list[dict[str, Any]]]] = []
        for m in messages:
            role = m.get("role")
            if role == "assistant":
                for call in m.get("tool_calls") or []:
                    calls[call["id"]] = call
                cont = m.get("_continuation") or {}
                if cont.get("protocol") == "gemini":
                    turns.append(("assistant", [{"type": "provider_content", **cont["provider_content"]}]))
                else:
                    turns.append(("assistant", [{"type": "text", "text": m.get("content") or ""}]))
            elif role == "tool" and not m.get("_synthetic"):
                response = {"type": "function_response", "name": m["name"], "response": _structured(m["content"])}
                provider_id = (calls.get(m.get("tool_call_id")) or {}).get("provider_id")
                if provider_id:
                    response["id"] = provider_id
                turns.append(("user", [response]))
                if m.get("_images"):
                    turns.append(("user", [{"type": "text", "text": f"Screenshot from {m['name']}"}, *m["_images"]]))
            elif role == "tool":
                text = f"Automatic pre-search (not requested by you) — RESULT for {m['name']}:\n{m['content']}"
                turns.append(("user", [{"type": "text", "text": text}, *(m.get("_images") or [])]))
            elif m.get("_status"):
                turns.append(("user", [{"type": "text", "text": m["content"]}]))
            else:
                content = m.get("content")
                turns.append((role or "user", content if isinstance(content, list)
                              else [{"type": "text", "text": str(content or "")}]))
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for role, parts in turns:
            if out[-1]["role"] == role:
                out[-1]["content"] = [*out[-1]["content"], *parts]
            else:
                out.append({"role": role, "content": list(parts)})
        return out

    def named_tool(self, tools: list[dict[str, Any]] | None, error_text: str) -> str | None:
        index = tool_schema.index_in(error_text, _DECLARATION_INDEX)   # declarations are `tools`, in order
        tools = tools or []
        if index is None or index >= len(tools):
            return None
        return (tools[index].get("function") or {}).get("name")

    def _payload(self, messages: list[dict[str, Any]], temperature: float,
                 tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        system, contents = self._to_contents(messages)
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 8192},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            declarations = []
            for tool in tools:
                function = tool.get("function") or {}
                if tool.get("type") != "function" or not function.get("name"):
                    raise ValueError("Gemini tools require a named function declaration")
                declarations.append({
                    "name": function["name"], "description": function.get("description") or "",
                    # 0.1.62 F3: an MCP server's schema reshaped to what all providers accept.
                    "parametersJsonSchema": tool_schema.for_tool(
                        function["name"], function.get("parameters") or {"type": "object"}, "gemini"),
                })
            payload["tools"] = [{"functionDeclarations": declarations}]
        return payload

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        url = f"{self.base_url}/models/{self.model}:generateContent"
        # Use a generous read timeout — Gemini thinking models (e.g. 2.5 Pro) can
        # hold the connection for 120 s+ before returning the first token.
        timeout = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0)
        from arslan.execution_budget import model_request
        payload = self._payload(messages, temperature, tools)
        if tool_choice == "none" and payload.get("tools"):
            # The forced wrap-up keeps the same declarations and may not call one (K1).
            payload["toolConfig"] = {"functionCallingConfig": {"mode": "NONE"}}
        payload["generationConfig"]["maxOutputTokens"] = model_request(8192)
        from arslan.execution_checkpoint import save
        await save("before_model")
        data = await param_heal.send(self.endpoint_fingerprint(), payload,
                                     lambda p: self._post(url, p, timeout))
        return self._parse_response(data)

    async def _post(self, url: str, payload: dict[str, Any], timeout: httpx.Timeout) -> dict[str, Any]:
        """One non-streamed send; param_heal may resend a changed payload."""
        evidence = await request_evidence.begin(payload)
        async with self._client() as client:
            response = await client.post(
                url, json=payload,
                headers=self._headers(), timeout=timeout,
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
            return response.json()

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
        from arslan.execution_budget import model_request
        payload = self._payload(messages, temperature)
        payload["generationConfig"]["maxOutputTokens"] = model_request(8192)
        from arslan.execution_checkpoint import save
        await save("before_model")
        async for piece in param_heal.stream(self.endpoint_fingerprint(), payload,
                                             lambda p: self._stream_attempt(url, p, timeout)):
            yield piece

    async def _stream_attempt(self, url: str, payload: dict[str, Any],
                              timeout: httpx.Timeout) -> AsyncIterator[str]:
        """One streamed send; param_heal may resend it before its first byte."""
        tin: int | None = None
        tout: int | None = None
        evidence = await request_evidence.begin(payload)
        async with self._client() as client:
            async with client.stream(
                "POST", url, json=payload,
                headers=self._headers(), timeout=timeout,
            ) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as _exc:
                    await provider_errors.read_body(_exc)
                    # Carry the provider's OWN explanation, not just the status
                    # line — see providers/errors.py for why this matters.
                    raise httpx.HTTPStatusError(
                        provider_errors.with_body(_exc),
                        request=_exc.request, response=_exc.response) from None
                await request_evidence.acknowledge(evidence)
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
        candidates = data.get("candidates") or []
        parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
        calls = []
        for index, part in enumerate(parts):
            function = part.get("functionCall")
            if function is None:
                continue
            if not isinstance(function.get("args", {}), dict):
                raise ValueError("Gemini functionCall args must be an object")
            calls.append({"id": function.get("id") or f"gemini_{index}", "type": "function",
                          "provider_id": function.get("id"),
                          "function": {"name": function.get("name", ""),
                                       "arguments": function.get("args") or {}},
                          "arguments_raw": json.dumps(function.get("args") or {}, ensure_ascii=False)})
        finish = (candidates[0].get("finishReason") if candidates else None)
        if finish == "MAX_TOKENS":
            finish_reason = "length"
        elif finish in _GEMINI_FILTERED:
            finish_reason = "content_filter"
        elif finish == "STOP" or (finish is None and calls):
            # Gemini reports STOP for a turn that ends in function calls.
            finish_reason = "tool_calls" if calls else "stop"
        else:
            finish_reason = str(finish).lower() if finish else None
        return LLMResponse(
            role="assistant",
            content=text or None,
            tool_calls=calls,
            provider_content={"provider": "gemini", "parts": parts} if calls else None,
            usage=data.get("usageMetadata", {}) or {},
            finish_reason=finish_reason,
        )


_GEMINI_FILTERED = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}


def _structured(text: str) -> dict[str, Any]:
    """A function response is an object: the result's own JSON object, else {"output": text}."""
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        value = None
    return value if isinstance(value, dict) else {"output": text}


def _first_text(obj: dict[str, Any]) -> str:
    """Join the text parts of the first candidate in a Gemini response chunk."""
    candidates = obj.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))
