#!/usr/bin/env python3
"""Ruling ②A — the live acceptance for G1, run by the user against a real key.

WHY THIS IS A SCRIPT AND NOT A TEST: it spends money and needs a real
Anthropic API key. Neither belongs to me. The unit suite proves the translation
and the parsing; it CANNOT prove that Anthropic accepts this payload and that a
real model then calls a tool — and "green units, silent failure on a real
machine" is the exact shape of the bug G1 exists to fix.

WHAT IT PROVES, and the order matters:

  ⓪ the probe can fail        — send a tool-worthy prompt with NO tools and
                                assert no tool call comes back. If this step
                                does not behave, the rest proves nothing.
  ① the payload is accepted   — Anthropic does not 400 on tools + a plain-text
                                assistant history (the one claim in the spec
                                derived rather than measured).
  ② the model really calls    — a tool_use block comes back and parses into the
                                normalised shape.
  ③ the loop continues        — feeding the result back as NEUTRAL TEXT does not
                                trip the tool_use/tool_result pairing rule.
                                This is the assumption the cheap design rests on.

Usage:

    ANTHROPIC_API_KEY=sk-ant-... python scripts/g1_live_acceptance.py

Cost: four short messages. Nothing is written to your database, no Arslan
settings are read, and the key is taken from the environment and never logged.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arslan.llm.providers.anthropic_provider import AnthropicProvider  # noqa: E402

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather in a given city.",
        "parameters": {"type": "object",
                       "properties": {"city": {"type": "string"}},
                       "required": ["city"]},
    },
}]

ASK = "What is the weather in Ürümqi right now? Use the tool."


def _ok(msg: str) -> None:
    print(f"  PASS  {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL  {msg}")


async def main() -> int:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("ANTHROPIC_API_KEY is not set — nothing was sent.", file=sys.stderr)
        return 2

    p = AnthropicProvider(model=MODEL, api_key=key)
    failures = 0

    # ⓪ ------------------------------------------------------------------
    print("\n⓪ the probe can fail (same prompt, no tools)")
    r0 = await p.chat([{"role": "user", "content": ASK}], tools=None)
    if r0.tool_calls:
        _fail(f"a toolless request produced tool calls: {r0.tool_calls}")
        failures += 1
    else:
        _ok("no tools sent, no tool call returned — the probe discriminates")

    # ① + ② --------------------------------------------------------------
    print("\n①② the payload is accepted, and the model calls the tool")
    try:
        r1 = await p.chat([{"role": "user", "content": ASK}], tools=TOOLS)
    except Exception as exc:  # noqa: BLE001
        _fail(f"Anthropic rejected the request: {exc}")
        return 1
    _ok("Anthropic accepted a request carrying `tools`")

    if not r1.tool_calls:
        _fail("the model returned no tool call — schemas reached the wire but "
              "nothing came back; re-run before concluding (models may answer "
              "directly), and if it persists the parsing is wrong")
        return 1
    tc = r1.tool_calls[0]
    _ok(f"tool_use parsed: {tc['function']['name']}({json.dumps(tc['function']['arguments'])})")
    if tc["function"]["name"] != "get_weather":
        _fail(f"wrong tool name: {tc['function']['name']}")
        failures += 1

    # ③ ------------------------------------------------------------------
    # The load-bearing one. The history we send back contains a PLAIN TEXT
    # assistant turn and a PLAIN TEXT user turn — no tool_result block — exactly
    # as tool_loop._record_tool_result builds it. If Anthropic's pairing rule
    # applied to us, this request is where it would 400.
    print("\n③ the loop continues with tool results fed back as neutral text")
    history = [
        {"role": "user", "content": ASK},
        {"role": "assistant", "content": json.dumps(
            {"tool": "get_weather", "args": tc["function"]["arguments"]}, ensure_ascii=False)},
        {"role": "user", "content": "TOOL RESULT for get_weather:\n"
                                    '{"ok": true, "temp_c": 24, "sky": "clear"}\n'
                                    "Use this to continue: give your final answer."},
    ]
    try:
        r2 = await p.chat(history, tools=TOOLS)
    except Exception as exc:  # noqa: BLE001
        _fail(f"Anthropic rejected the follow-up: {exc}\n"
              "      ⇒ the spec's one DERIVED claim is wrong: the pairing "
              "constraint DOES apply, and the cheap design does not hold.")
        return 1
    _ok("accepted — no tool_result block required, so the pairing rule does not apply")
    if r2.content:
        _ok(f"final answer: {r2.content.strip()[:120]}")
    else:
        _fail("second step produced no content")
        failures += 1

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
