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

0.1.63 K1: the in-turn trajectory goes back natively (``build_trajectory_messages``):
each assistant turn is replayed as the API returned it (thinking, redacted_thinking,
text and tool_use, byte for byte, only to the endpoint+model+key that produced it), and
the next user message carries every ``tool_result`` of that batch, then the step's status
as its own text block. Nothing already sent is edited later (preserved thinking: an
edited prefix invalidates every later thinking block). Until K1b moves the in-turn
context trimming server-side, this stays off by default (``NATIVE_TRAJECTORY``); the
legacy text rendering (``trajectory.to_legacy``) is what Claude gets meanwhile.
"""
from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from arslan.llm.providers import errors as provider_errors
from arslan.llm import param_heal, request_evidence, tool_schema

from arslan.llm.cached_system import CachedSystem
from arslan.llm.providers.base import BaseLLMProvider
from arslan.models import LLMResponse

# Claude generation from the model id, both naming styles, platform prefixes
# ("anthropic.", "us.anthropic.") passing through: claude-sonnet-5-5,
# claude-opus-4-1-20250805, claude-sonnet-4-20250514 (4.0: the date is not a
# minor), claude-3-7-sonnet-20250219, claude-3-opus-20240229.
_CLAUDE_NEW = re.compile(r"claude-(?:opus|sonnet|haiku|fable|mythos)-(\d+)(?:-(\d{1,2}))?(?!\d)")
_CLAUDE_OLD = re.compile(r"claude-(\d+)(?:-(\d{1,2}))?-(?:opus|sonnet|haiku)")

# Claude 5 and later think when `thinking` is omitted. The switch that turns it
# off, per model (claude-api model-migration guide, 2026-10): Sonnet 5.5 answers
# "disabled" with a 400 and takes "between_tools"; Opus 5.5 and Fable refuse
# every off switch, so they are absent on purpose. Only the default effort is
# ever sent with these, which is "high" or below on all four — the ceiling for
# both switches.
_THINKING_OFF = {
    "claude-sonnet-5-5": {"type": "between_tools"},
    "claude-sonnet-5": {"type": "disabled"},
    "claude-opus-5": {"type": "disabled"},
    "claude-haiku-5-5": {"type": "disabled"},
}


# 0.1.63 K1a: Claude's native trajectory, built but off until K1b moves in-turn context trimming
# server-side (card point 12). K1b turns it on and deletes this switch.
NATIVE_TRAJECTORY = False

# Preserved thinking (claude-api model-migration guide, 2026-10): from the 5.5 generation and
# Fable / Mythos 5.1 a replayed thinking block whose conversation prefix changed is rejected (new
# accounts) or must be opted out of. "drop_block" asks the API to drop such blocks instead; it needs
# this beta and goes only with adaptive thinking (never with Sonnet 5.5's between_tools).
BINDING_BETA = "thinking-binding-controls-2026-08-01"
_DROP_BLOCK = {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
_FAMILY = re.compile(r"claude-(opus|sonnet|haiku|fable|mythos)-")
# Marks the system entry of a message list built by build_trajectory_messages (never sent).
_TRAJECTORY = "_trajectory"


def _claude_version(model: str) -> tuple[int, int] | None:
    """(major, minor) of a Claude model id; None when it cannot be placed."""
    m = _CLAUDE_NEW.search(model) or _CLAUDE_OLD.search(model)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None



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
        elif isinstance(b, dict) and b.get("type") == "text" and "text" not in b:
            out.append({"type": "text", "text": ""})
        else:
            # A text block passes through as it is: a replayed one may carry more than its text
            # (citations), and replayed assistant content must stay byte for byte (K1).
            out.append(b)
    return out

def _tool_input(call: dict[str, Any]) -> dict[str, Any]:
    if isinstance(call.get("arguments"), dict):
        return call["arguments"]
    try:
        parsed = json.loads(call.get("arguments_raw") or "{}")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _result_content(text: str, images: list[dict] | None) -> Any:
    """A tool_result's content: its text, plus its screenshots as image blocks."""
    if not images:
        return text
    return [{"type": "text", "text": text}, *_translate(images)]


def _blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        return list(content)
    return [{"type": "text", "text": str(content)}] if content not in (None, "") else []


_TOOL_INDEX = re.compile(r"\btools\.(\d+)\b")


class AnthropicProvider(BaseLLMProvider):
    DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
    ANTHROPIC_VERSION = "2023-06-01"
    # A non-streamed reply: same first-byte bound as the OpenAI-compatible path
    # (model_call.py relies on it). Was 60 s, short for a model that thinks first.
    TIMEOUT = httpx.Timeout(300.0, connect=15.0)

    def __init__(
        self,
        model: str,
        api_key: str = "",
        base_url: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(model=model, api_key=api_key, base_url=base_url or self.DEFAULT_BASE_URL)
        self._transport = transport
        # Thinking and the answer share max_tokens on Claude 5+, so the old flat
        # 4096 could be spent before the reply was written. Same opening budget
        # and length-cut ceiling as the OpenAI-compatible path; tool_loop's
        # _recover_truncation raises a cut request via chat(max_tokens=...).
        from arslan.llm.output_budget import for_endpoint
        budget = for_endpoint(self.base_url, model)
        self.max_tokens = budget.initial
        self.output_ceiling = max(self.max_tokens, budget.ceiling)

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def _is_claude(self) -> bool:
        return "claude" in self.model.lower()

    def _sends_sampling(self) -> bool:
        """Claude 4.6 and earlier take `temperature`. Opus 4.7 and every later
        Claude answer it with a 400 ("`temperature` is deprecated for this
        model.": Sonnet 5.x / Haiku 5.5 for any value but the default, the rest
        for any value), while all of them accept it omitted — so a Claude id that
        cannot be placed omits it too. A non-Claude model behind this protocol is
        not governed by Anthropic's rules and keeps what it was sent before."""
        if not self._is_claude():
            return True
        version = _claude_version(self.model.lower())
        return version is not None and version <= (4, 6)

    def _thinking_off(self) -> dict[str, str] | None:
        """The `thinking` value that provably keeps reasoning off: {} when nothing
        has to be sent (Claude 4.x and earlier think only when asked), the model's
        switch, or None when no switch exists (Opus 5.5, Fable) or the model
        cannot be placed."""
        if not self._is_claude():
            return None
        model = self.model.lower()
        version = _claude_version(model)
        if version is not None and version < (5, 0):
            return {}
        return _THINKING_OFF.get(model[model.find("claude-"):])

    def supports_bounded_critique(self) -> bool:
        return self._thinking_off() is not None

    def supports_native_trajectory(self) -> bool:
        return NATIVE_TRAJECTORY

    APPENDS_STATUS = True        # the step status is kept in the trajectory, never re-attached (K1)

    def _binds_thinking(self) -> bool:
        """Whether this model checks the conversation prefix of replayed thinking blocks."""
        model = self.model.lower()
        version, family = _claude_version(model), _FAMILY.search(model)
        if version is None or family is None:
            return False
        return version >= (5, 5) or (family.group(1) in ("fable", "mythos") and version >= (5, 1))

    def build_trajectory_messages(self, system: Any, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Neutral trajectory (arslan/llm/trajectory.py) -> Anthropic messages, append-only.

        assistant: the content blocks the API returned, verbatim (thinking and its signature
        included), when they came from this endpoint+model+key and their tool_use ids are the
        calls run; otherwise rebuilt from text + tool_use, without thinking. Tool results: one
        tool_result per call, in the user message right after, before anything else. A host-run
        result was never requested by the model: user text. A step status (trajectory.status):
        its own text block after that step's results. Consecutive same-role messages merge."""
        endpoint = self.endpoint_fingerprint()
        turns: list[tuple[str, Any]] = []
        for m in messages:
            role = m.get("role")
            if role == "assistant":
                calls = m.get("tool_calls") or []
                cont = m.get("_continuation") or {}
                verbatim = cont.get("content") if (cont.get("protocol") == "anthropic"
                                                   and cont.get("endpoint") == endpoint) else None
                if isinstance(verbatim, list) and [b.get("id") for b in verbatim if b.get("type") == "tool_use"] \
                        == [c["id"] for c in calls]:
                    turns.append(("assistant", list(verbatim)))
                elif calls:
                    turns.append(("assistant", [*_blocks(m.get("content")), *[
                        {"type": "tool_use", "id": c["id"], "name": c["name"], "input": _tool_input(c)}
                        for c in calls]]))
                else:
                    turns.append(("assistant", m.get("content") or ""))
            elif role == "tool" and m.get("_synthetic"):
                text = f"Automatic pre-search (not requested by you) — RESULT for {m['name']}:\n{m['content']}"
                turns.append(("user", [{"type": "text", "text": text}, *_translate(m.get("_images") or [])]))
            elif role == "tool":
                turns.append(("user", [{"type": "tool_result", "tool_use_id": m["tool_call_id"],
                                        "content": _result_content(m["content"], m.get("_images"))}]))
            elif m.get("_status"):
                turns.append(("user", [{"type": "text", "text": m["content"]}]))
            else:
                turns.append((role or "user", _translate(m.get("content"))))
        out: list[dict[str, Any]] = [{"role": "system", "content": system, _TRAJECTORY: True}]
        for role, content in turns:
            last = out[-1]
            if last["role"] == role and role != "system":
                last["content"] = [*_blocks(last["content"]), *_blocks(content)]
            else:
                out.append({"role": role, "content": content})
        return out

    def _client(self) -> httpx.AsyncClient:
        if self._transport is not None:
            return httpx.AsyncClient(transport=self._transport)
        return httpx.AsyncClient()

    def _headers(self, betas: list[str] | None = None) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "anthropic-version": self.ANTHROPIC_VERSION,
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        if betas:
            headers["anthropic-beta"] = ",".join(betas)
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
                # 0.1.62 F3: an MCP server's schema reshaped to what Anthropic accepts.
                "input_schema": tool_schema.for_tool(
                    name, fn.get("parameters") or t.get("input_schema") or {}, "anthropic"),
            })
        return out or None

    def named_tool(self, tools: list[dict[str, Any]] | None, error_text: str) -> str | None:
        # "tools.137.custom.input_schema: …" (field report 2026-10-14): the position in the
        # translated list, where tools without a name were skipped.
        index = tool_schema.index_in(error_text, _TOOL_INDEX)
        sent = self._translate_tools(tools) or []
        return sent[index]["name"] if index is not None and index < len(sent) else None

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
        # Tools are serialized below (G1) and render before the system prefix; no cache_control
        # is put on the last tool (D3), so a changed tool list costs the whole prefix.
        native = any(m.get(_TRAJECTORY) for m in messages if m.get("role") == "system")
        system, convo = self._split_system(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": convo,
        }
        if self._sends_sampling():
            payload["temperature"] = temperature
        if system:
            payload["system"] = system
        from arslan.llm.request_policy import (
            CRITIQUE_MAX_OUTPUT_TOKENS, CRITIQUE_TEMPERATURE, bounded_critique)
        if bounded_critique.get() and not tools:
            if "temperature" in payload:
                payload["temperature"] = CRITIQUE_TEMPERATURE
            off = self._thinking_off()
            # Only a model that provably does not think gets the short cap; a
            # thinking model would spend it on reasoning and return nothing (0.1.40).
            if off is not None:
                payload["max_tokens"] = min(self.max_tokens, CRITIQUE_MAX_OUTPUT_TOKENS)
                if off:
                    payload["thinking"] = off
        # Order matters for the cache, not just for readability: Anthropic renders
        # tools -> system -> messages, and the breakpoint sits at the system
        # prefix, so anything unstable in `tools` invalidates everything after it.
        # The stability requirement is discharged upstream (resolve_tools orders
        # its rows) and asserted by test_tool_transport.
        translated = self._translate_tools(tools)
        if translated:
            payload["tools"] = translated
        if native and self._binds_thinking() and "thinking" not in payload:
            # 0.1.63 K1: only native requests replay thinking; the legacy request stays as it was.
            payload["thinking"] = json.loads(json.dumps(_DROP_BLOCK))
            payload["_betas"] = [BINDING_BETA]
        return payload

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        """`max_tokens` raises this one request after a length cut. `tool_choice="none"`: the
        forced wrap-up step keeps the same tools (same prefix) and may not call one (K1)."""
        from arslan.execution_budget import model_request
        payload = self._payload(messages, temperature, tools)
        if tool_choice == "none" and payload.get("tools"):
            payload["tool_choice"] = {"type": "none"}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        payload["max_tokens"] = model_request(payload["max_tokens"])
        from arslan.execution_checkpoint import save
        await save("before_model")
        data = await param_heal.send(self.endpoint_fingerprint(), payload, self._post)
        response = self._parse_response(data)
        _note_transformations(response.input_transformations)
        return response

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """One non-streamed send; param_heal may resend a changed payload."""
        betas = payload.get("_betas") or []
        payload = {k: v for k, v in payload.items() if k != "_betas"}
        evidence = await request_evidence.begin(payload)
        async with self._client() as client:
            response = await client.post(
                f"{self.base_url}/messages",
                json=payload,
                headers=self._headers(betas),
                timeout=self.TIMEOUT,
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
        payload = {**self._payload(messages, temperature), "stream": True}
        from arslan.execution_budget import model_request
        payload["max_tokens"] = model_request(payload["max_tokens"])
        from arslan.execution_checkpoint import save
        await save("before_model")
        async for piece in param_heal.stream(self.endpoint_fingerprint(), payload, self._stream_attempt):
            yield piece

    async def _stream_attempt(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        """One streamed send; param_heal may resend it before its first byte."""
        betas = payload.get("_betas") or []
        payload = {k: v for k, v in payload.items() if k != "_betas"}
        evidence = await request_evidence.begin(payload)
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
                headers=self._headers(betas),
                timeout=60.0,
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

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        # G1. `tool_use` blocks become the SAME normalised shape openai_provider
        # emits, because run_native reads tc["function"]["name"]/["arguments"] and
        # must not have to know which provider answered. `input` arrives already
        # decoded here (OpenAI sends a JSON string and that parser decodes it), so
        # arguments is a dict on both paths.
        tool_calls = [
            {"id": b.get("id", ""), "type": "function",
             "function": {"name": b.get("name", ""), "arguments": b.get("input") or {}},
             "arguments_raw": json.dumps(b.get("input") or {}, ensure_ascii=False)}
            for b in blocks if b.get("type") == "tool_use"
        ]
        stop = data.get("stop_reason")
        # 0.1.63 K1: the whole assistant content, order unchanged, for replay within this turn to
        # this endpoint+model+key only (thinking blocks must come back byte for byte).
        replay = any(b.get("type") in ("tool_use", "thinking", "redacted_thinking") for b in blocks)
        transformations = data.get("input_transformations")
        return LLMResponse(
            role=data.get("role", "assistant"),
            content=text or None,
            tool_calls=tool_calls,
            usage=data.get("usage", {}) or {},
            finish_reason=_ANTHROPIC_FINISH.get(stop, str(stop).lower()) if stop else None,
            continuation=({"protocol": "anthropic", "endpoint": self.endpoint_fingerprint(),
                           "content": json.loads(json.dumps(blocks))} if replay else None),
            input_transformations=transformations if isinstance(transformations, list) else None,
        )


_ANTHROPIC_FINISH = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
                     "tool_use": "tool_calls", "refusal": "content_filter"}


def _note_transformations(entries: list[dict[str, Any]] | None) -> None:
    """Dropped thinking blocks go to the run record as counts per reason, never their content."""
    if not entries:
        return
    from arslan.execution_budget import current
    budget = current()
    if budget is None:
        return
    counts: dict[str, int] = {}
    for entry in entries:
        if isinstance(entry, dict) and entry.get("type") == "thinking_dropped":
            reason = str(entry.get("reason") or "unknown")
            counts[reason] = counts.get(reason, 0) + 1
    for reason, count in counts.items():
        budget.note_context("thinking_dropped", reason=reason, count=count)
