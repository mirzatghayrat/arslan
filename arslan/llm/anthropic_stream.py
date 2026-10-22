"""Assemble a Claude (Messages API) SSE reply into the reply the non-streamed API returns (0.1.63 K8b).

`AnthropicProvider._parse_response` reads the result unchanged, so a streamed reply and a whole one parse the
same: every content block in index order, thinking blocks with their signatures as sent (they are replayed
byte for byte within the turn, K1), tool calls with their arguments decoded, the stop reason, the usage
(message_start's, with message_delta's cumulative counts over it), `input_transformations` (message_start, or
message_delta after a fallback) and `context_management` (message_delta). Only answer text goes to `on_text`
as it arrives: never thinking, never tool arguments.

- **Idle watchdog** (`stream_assembly.IDLE_S`), no total limit here: the turn's remaining time bounds the
  whole request (model_call.call_with_recovery). A `ping` counts as alive: under the default thinking
  display, Claude's reasoning streams nothing, and pings are what a generating server sends meanwhile
  (⓪Plan's Q2).
- **An `error` event** raises the HTTP status its type means, so model_call classifies it as if it had come
  before the stream (Q3). Whether it may be resent once text went out is the loop's call (K8a, `_once_shown`).
- **A stream that ends before `message_stop`** is never taken as an answer.
- **A delta this version does not know, or a `data:` line it cannot parse** (a dropped signature_delta
  would make the next request a 400), leaves the reply possibly incomplete: it is marked NOT_VERBATIM
  (replayed rebuilt, without thinking) or, when it calls a tool (whose next request might need that
  thinking), refused with stream_assembly.UnreadableReply, which is never resent (Q5; ⓪Plan's review).
"""
from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Callable
from typing import Any

import httpx

from arslan.llm import stream_assembly

#: Set on a reply whose blocks may not be as the API produced them: never replayed verbatim.
NOT_VERBATIM = "_not_verbatim"
# Anthropic's error types and their statuses (claude-api error codes); any other type is a server error.
_STATUS = {"invalid_request_error": 400, "authentication_error": 401, "billing_error": 402,
           "permission_error": 403, "not_found_error": 404, "request_too_large": 413,
           "rate_limit_error": 429, "api_error": 500, "overloaded_error": 529}


class _Assembler:
    def __init__(self, on_text: Callable[[str], None] | None) -> None:
        self.on_text = on_text
        self.message: dict[str, Any] = {}
        self.blocks: dict[int, dict[str, Any]] = {}
        self.arguments: dict[int, list[str]] = {}
        self.unknown = False
        self.stopped = False

    def feed(self, frame: dict[str, Any], request: httpx.Request) -> None:
        kind = frame.get("type")
        if kind == "message_start":
            self.message = copy.deepcopy(frame.get("message") or {})
        elif kind == "content_block_start":
            index = frame.get("index")
            self.blocks[index] = copy.deepcopy(frame.get("content_block") or {})
            if self.blocks[index].get("type") == "tool_use":
                self.arguments[index] = []
        elif kind == "content_block_delta":
            self._delta(frame.get("index"), frame.get("delta") or {})
        elif kind == "content_block_stop":
            self._close(frame.get("index"))
        elif kind == "message_delta":
            delta = frame.get("delta") or {}
            self.message.update({key: delta[key] for key in ("stop_reason", "stop_sequence") if key in delta})
            usage = {key: value for key, value in (frame.get("usage") or {}).items() if value is not None}
            self.message["usage"] = {**(self.message.get("usage") or {}), **usage}
            self.message.update({key: value for key, value in frame.items() if key not in ("type", "delta", "usage")})
        elif kind == "message_stop":
            self.stopped = True
        elif kind == "error":
            raise _error(frame, request)

    def _delta(self, index: Any, delta: dict[str, Any]) -> None:
        block, kind = self.blocks.get(index), delta.get("type")
        if block is None:
            self.unknown = True
        elif kind == "text_delta":
            text = delta.get("text") or ""
            block["text"] = (block.get("text") or "") + text
            if text and self.on_text is not None:
                self.on_text(text)
        elif kind == "input_json_delta" and index in self.arguments:
            self.arguments[index].append(delta.get("partial_json") or "")
        elif kind == "thinking_delta":
            block["thinking"] = (block.get("thinking") or "") + (delta.get("thinking") or "")
        elif kind == "signature_delta":
            block["signature"] = (block.get("signature") or "") + (delta.get("signature") or "")
        elif kind == "citations_delta":
            block.setdefault("citations", []).append(delta.get("citation"))
        else:
            self.unknown = True

    def _close(self, index: Any) -> None:
        if index not in self.arguments:
            return
        raw = "".join(self.arguments.pop(index))
        try:
            self.blocks[index]["input"] = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            raise httpx.RemoteProtocolError("a streamed tool call's arguments did not parse") from None

    def result(self) -> dict[str, Any]:
        if not self.stopped:
            raise httpx.RemoteProtocolError("model stream ended before the reply finished")
        content = [self.blocks[index] for index in sorted(self.blocks)]
        if self.unknown and any(block.get("type") == "tool_use" for block in content):
            raise stream_assembly.UnreadableReply(
                "the reply streamed something this version cannot read (an unknown delta or line); "
                "its tool call is not run")
        return {**self.message, "content": content, **({NOT_VERBATIM: True} if self.unknown else {})}


def _error(frame: dict[str, Any], request: httpx.Request) -> httpx.HTTPStatusError:
    error = frame.get("error") or {}
    kind = str(error.get("type") or "error")
    status = _STATUS.get(kind, 500)
    response = httpx.Response(status, json=frame, request=request)
    return httpx.HTTPStatusError(f"{status} {kind} in the stream: {error.get('message') or ''}".strip(),
                                 request=request, response=response)


async def assemble(response: httpx.Response, on_text: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Read a Messages SSE body to its end under the idle watchdog; `on_text` gets each piece of answer text."""
    try:
        request = response.request
    except RuntimeError:                  # a response built without its request (tests)
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    assembler = _Assembler(on_text)
    lines = response.aiter_lines().__aiter__()
    last_progress = stream_assembly.monotonic()
    while True:
        budget = stream_assembly.IDLE_S - (stream_assembly.monotonic() - last_progress)
        if budget <= 0:
            raise stream_assembly.StreamStalled(f"no model output for {stream_assembly.IDLE_S:.0f}s (stream stalled)")
        try:
            raw = await asyncio.wait_for(lines.__anext__(), timeout=budget)
        except StopAsyncIteration:
            break
        except TimeoutError:
            raise stream_assembly.StreamStalled(
                f"no model output for {stream_assembly.IDLE_S:.0f}s (stream stalled)") from None
        line = raw.strip()
        if not line.startswith("data:"):
            continue                      # "event:" names and blank lines
        last_progress = stream_assembly.monotonic()
        try:
            frame = json.loads(line[len("data:"):].strip())
        except json.JSONDecodeError:
            assembler.unknown = True      # what it carried is lost: the reply may be incomplete
            continue
        assembler.feed(frame, request)
        if assembler.stopped:
            break
    return assembler.result()
