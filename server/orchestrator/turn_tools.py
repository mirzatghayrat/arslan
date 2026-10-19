"""A turn's tools, summarized for the next turn's history (K2).

The answer is stored with this block after the reply in arslan_messages.content, which the model's
history reads; display_content keeps the reply alone, which every reader shows. One line per call:
the tool, its key argument, and what came back. External content (untrusted.counts_as_external:
pages, MCP, files read, memory recall) is recorded by its source only: its text in a later turn's
history would read as something Arslan itself said, and its instructions with it.
"""
from __future__ import annotations

import json
import os

OPEN, CLOSE = "<turn_tools>", "</turn_tools>"
_RESULT_CHARS = 500
# Bounds one turn's block (about 3.5k estimated tokens at most): a long tool run must not eat the
# next turns' history budget. The rest is counted, not listed.
MAX_LINES = 20
_ARG_CHARS = 160
_KEY_ARGS = ("url", "path", "query", "command", "code", "name", "app", "title", "target", "id")
_RESULT_TEXT = ("stdout", "output", "content", "text", "result", "summary")


def enabled() -> bool:
    """The switch back for v0.1.63. Deleted in v0.1.64 if v0.1.63 has been installed 7 days
    without needing it and M3 #3 and #11 pass (K2 card)."""
    return os.environ.get("ARSLAN_TURN_TOOL_SUMMARY", "").lower() not in {"off", "0", "false"}


def _clip(text: str, limit: int) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _key_arg(args: dict) -> str:
    for key in _KEY_ARGS:
        if isinstance(args.get(key), str) and args[key].strip():
            return f"{key}={_clip(args[key], _ARG_CHARS)}"
    first = next((f"{k}={_clip(v, _ARG_CHARS)}" for k, v in args.items() if isinstance(v, str) and v.strip()), "")
    return first


def _outcome(result: dict) -> str:
    if not result.get("ok", True):
        return "failed: " + _clip(result.get("error") or "error", _ARG_CHARS)
    saved = result.get("full_output_path")
    if saved:
        return f"full output saved to {saved}"
    for key in _RESULT_TEXT:
        if isinstance(result.get(key), str) and result[key].strip():
            return _clip(result[key], _RESULT_CHARS)
    rest = {k: v for k, v in result.items() if k not in {"ok", "artifact", "receipt"}}
    return _clip(json.dumps(rest, ensure_ascii=False, default=str), _RESULT_CHARS) if rest else "ok"


def _line(call: dict) -> str:
    from server.orchestrator.untrusted import counts_as_external
    tool = str(call.get("tool") or "?")
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    result = call.get("result") if isinstance(call.get("result"), dict) else {}
    head = f"- {tool}" + (f" {_key_arg(args)}" if _key_arg(args) else "")
    if counts_as_external(tool, args):
        failed = "" if result.get("ok", True) else f": {_outcome(result)}"
        return head + (failed or ": external content, source only")
    return f"{head}: {_outcome(result)}"


def block(tool_trace: list[dict] | None) -> str:
    """The block for one turn ("" without tool calls or with the switch off)."""
    calls = [call for call in tool_trace or [] if isinstance(call, dict)]
    if not calls or not enabled():
        return ""
    lines = [_line(call) for call in calls[:MAX_LINES]]
    if len(calls) > MAX_LINES:
        lines.append(f"- … {len(calls) - MAX_LINES} more tool calls")
    return "\n".join([OPEN, *lines, CLOSE])
