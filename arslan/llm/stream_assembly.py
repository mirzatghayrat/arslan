"""Assemble an OpenAI-compatible SSE reply into one response, with an idle
watchdog (0.1.49 S7, design section 6).

Streaming exists here for one reason: to tell a stalled request from a long
one. A thinking model may legitimately run for minutes, so a total timeout
either kills real work or waits forever on a dead connection. Progress is
measured on real deltas only (reasoning, content, tool-call arguments); SSE
comments such as ": keep-alive" and empty frames are not progress.

run_native still receives one complete reply: nothing executes from a partial
stream, so a stalled or interrupted stream is simply re-sent (and billed).
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

IDLE_S = 90.0                 # no real delta for this long = stalled
monotonic = time.monotonic    # injectable for tests


class StreamStalled(TimeoutError):
    """No real delta within IDLE_S. A TimeoutError, so model_call classifies it
    as a stall (retried once)."""


class StreamAssembler:
    """Fold chat.completion.chunk frames into a non-streamed response dict."""

    def __init__(self) -> None:
        self.content: list[str] = []
        self.reasoning: list[str] = []
        self.reasoning_alt: list[str] = []          # OpenRouter "reasoning"
        self.reasoning_details: list[Any] = []
        self.calls: dict[int, dict[str, Any]] = {}
        self.finish_reason: str | None = None
        self.usage: dict[str, Any] = {}
        self.role = "assistant"
        self.done = False

    def feed(self, frame: dict[str, Any]) -> bool:
        """Apply one decoded frame; True when it carried a real delta."""
        progress = False
        if isinstance(frame.get("usage"), dict):
            self.usage = frame["usage"]
        for choice in frame.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("role"):
                self.role = delta["role"]
            for key, sink in (("content", self.content), ("reasoning_content", self.reasoning),
                              ("reasoning", self.reasoning_alt)):
                piece = delta.get(key)
                if isinstance(piece, str) and piece:
                    sink.append(piece)
                    progress = True
            details = delta.get("reasoning_details")
            if isinstance(details, list) and details:
                self.reasoning_details.extend(details)
                progress = True
            for tc in delta.get("tool_calls") or []:
                index = tc.get("index", len(self.calls))
                slot = self.calls.setdefault(index, {"id": "", "type": "function", "name": "", "arguments": ""})
                if tc.get("id") and not slot["id"]:
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name") and not slot["name"]:
                    slot["name"] = fn["name"]
                if isinstance(fn.get("arguments"), str) and fn["arguments"]:
                    slot["arguments"] += fn["arguments"]
                progress = True
            if choice.get("finish_reason"):
                self.finish_reason = choice["finish_reason"]
        return progress

    def result(self) -> dict[str, Any]:
        message: dict[str, Any] = {"role": self.role, "content": "".join(self.content)}
        if self.reasoning:
            message["reasoning_content"] = "".join(self.reasoning)
        if self.reasoning_alt:
            message["reasoning"] = "".join(self.reasoning_alt)
        if self.reasoning_details:
            message["reasoning_details"] = self.reasoning_details
        if self.calls:
            message["tool_calls"] = [
                {"id": slot["id"], "type": "function",
                 "function": {"name": slot["name"], "arguments": slot["arguments"]}}
                for _, slot in sorted(self.calls.items())]
        return {"choices": [{"message": message, "finish_reason": self.finish_reason}],
                "usage": self.usage}


async def assemble(response: httpx.Response) -> dict[str, Any]:
    """Read an SSE body to completion under the idle watchdog."""
    assembler = StreamAssembler()
    lines = response.aiter_lines().__aiter__()
    last_progress = monotonic()
    while True:
        budget = IDLE_S - (monotonic() - last_progress)
        if budget <= 0:
            raise StreamStalled(f"no model output for {IDLE_S:.0f}s (stream stalled)")
        try:
            raw = await asyncio.wait_for(lines.__anext__(), timeout=budget)
        except StopAsyncIteration:
            break
        except TimeoutError:
            raise StreamStalled(f"no model output for {IDLE_S:.0f}s (stream stalled)") from None
        line = raw.strip()
        if not line.startswith("data:"):
            continue                      # ": keep-alive" comments, blank lines, event: names
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            assembler.done = True
            break
        try:
            frame = json.loads(data)
        except json.JSONDecodeError:
            continue
        if assembler.feed(frame):
            last_progress = monotonic()
    if not assembler.done and assembler.finish_reason is None:
        # The connection ended mid-reply: incomplete, never parse it as an answer.
        raise httpx.RemoteProtocolError("model stream ended before the reply finished")
    return assembler.result()
