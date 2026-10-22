"""Assemble a Gemini `:streamGenerateContent?alt=sse` reply into one GenerateContentResponse (0.1.63 K8c).

Each `data:` line is a partial response: the first candidate's new parts, and on the last line its
`finishReason`; `usageMetadata` is cumulative. The parts are kept in the order they came and as they were
sent, so a `thoughtSignature` stays on the part it belongs to (a function call, or an empty text part at the
end): `GeminiProvider` replays them as `provider_content` (⓪Plan's Q3). The stream splits text into more
parts than a whole reply has; `_parse_response` joins it the same way. Only non-thought text goes to
`on_text`, as it arrives.

- **Idle bound** IDLE_S (300 s, the per-read timeout Gemini had): it sends nothing while it thinks, and
  there are no keep-alive events to count (Q2). The turn's remaining time bounds the whole request.
- **An `error` object** raises the HTTP status in its `code` (500 when it has none), so model_call
  classifies it as if it had come before the stream (Q4); no resend once text went out (K8a).
- **A stream that ends before a finishReason** (and without a blocked prompt) is never an answer.
- **A part or a line this version does not know** in a reply that calls a function: refused with
  stream_assembly.UnreadableReply, never resent; the call does not run (Q3). Without a call nothing of the
  reply is replayed, so it simply answers.
"""
from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Callable
from typing import Any

import httpx

from arslan.llm import stream_assembly

IDLE_S = 300.0
# The part fields a model reply carries (the Gemini API's Part); anything else is a part we cannot read.
_KNOWN = frozenset({"text", "thought", "thoughtSignature", "functionCall", "inlineData", "fileData",
                    "executableCode", "codeExecutionResult"})


async def assemble(response: httpx.Response, on_text: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Read the SSE body to its end under the idle bound; `on_text` gets each piece of answer text."""
    try:
        request = response.request
    except RuntimeError:                  # a response built without its request (tests)
        request = httpx.Request("POST", "https://generativelanguage.googleapis.com/")
    parts: list[dict[str, Any]] = []
    top: dict[str, Any] = {}              # the response's own fields, last chunk wins
    candidate: dict[str, Any] = {}        # the first candidate's fields but its parts, last chunk wins
    unknown = False
    lines = response.aiter_lines().__aiter__()
    last_progress = stream_assembly.monotonic()
    while True:
        budget = IDLE_S - (stream_assembly.monotonic() - last_progress)
        if budget <= 0:
            raise stream_assembly.StreamStalled(f"no model output for {IDLE_S:.0f}s (stream stalled)")
        try:
            raw = await asyncio.wait_for(lines.__anext__(), timeout=budget)
        except StopAsyncIteration:
            break
        except TimeoutError:
            raise stream_assembly.StreamStalled(f"no model output for {IDLE_S:.0f}s (stream stalled)") from None
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        last_progress = stream_assembly.monotonic()
        try:
            frame = json.loads(line[len("data:"):].strip())
        except json.JSONDecodeError:
            unknown = True                # what it carried is lost: the reply may be incomplete
            continue
        if isinstance(frame.get("error"), dict):
            raise _error(frame, request)
        top.update({key: value for key, value in frame.items() if key != "candidates"})
        first = next((c for c in frame.get("candidates") or [] if c.get("index", 0) == 0), None)
        if first is None:
            continue
        candidate.update({key: value for key, value in first.items() if key != "content"})
        for part in (first.get("content") or {}).get("parts") or []:
            unknown = unknown or not set(part) <= _KNOWN
            parts.append(copy.deepcopy(part))
            text = part.get("text")
            if text and not part.get("thought") and on_text is not None:
                on_text(text)
    blocked = bool((top.get("promptFeedback") or {}).get("blockReason"))
    if not candidate.get("finishReason") and not blocked:
        raise httpx.RemoteProtocolError("model stream ended before the reply finished")
    if unknown and any("functionCall" in part for part in parts):
        raise stream_assembly.UnreadableReply(
            "the reply streamed something this version cannot read (an unknown part or line); "
            "its function call is not run")
    if not candidate:
        return top
    return {**top, "candidates": [{**candidate, "content": {"role": "model", "parts": parts}}]}


def _error(frame: dict[str, Any], request: httpx.Request) -> httpx.HTTPStatusError:
    error = frame["error"]
    code = error.get("code")
    status = code if isinstance(code, int) and 400 <= code <= 599 else 500
    response = httpx.Response(status, json=frame, request=request)
    return httpx.HTTPStatusError(f"{status} {error.get('status') or 'error'} in the stream: "
                                 f"{error.get('message') or ''}".strip(), request=request, response=response)
