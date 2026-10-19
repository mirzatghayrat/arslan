"""A turn's tools, summarized for the next turn's history (K2).

The answer is stored with this block after the reply in arslan_messages.content, which the model's
history reads; display_content keeps the reply alone, which every reader shows. One line per call:
the tool, an identifying argument, and its outcome. Result text is kept only for an allowlist (file
names); external content (untrusted.counts_as_external, or a result marked external) is recorded by
its source only: its text in a later turn's history would read as something Arslan itself said, and
its instructions with it.
"""
from __future__ import annotations

import json
import os

OPEN, CLOSE = "<turn_tools>", "</turn_tools>"
_RESULT_CHARS = 500
_ARG_CHARS = 160
_COMMAND_CHARS = 80
# Bounds one turn's block (about 3.5k estimated tokens at most): a long tool run must not eat the
# next turns' history budget. The rest is counted, not listed.
MAX_LINES = 20
# Result TEXT is kept only for these: their output is the user's own file names. Every other tool is
# recorded by its outcome. An allowlist, not a blocklist (③Hands' review of K2a): untrusted's fixed
# list has no Mac or Hands tool, so window text, AppleScript and Shortcut output, and command or
# code output would otherwise have been persisted as something Arslan said.
_RESULT_TOOLS = frozenset({"list_dir", "search_files"})
# Arguments recorded: identifiers, never bodies (a script, code, text typed or written, a label).
_KEY_ARGS = ("path", "url", "query", "name", "title")
_HANDS = ("desktop_", "mac_")


def enabled() -> bool:
    """The switch back for v0.1.63. Deleted in v0.1.64 if v0.1.63 has been installed 7 days
    without needing it and M3 #3 and #11 pass (K2 card)."""
    return os.environ.get("ARSLAN_TURN_TOOL_SUMMARY", "").lower() not in {"off", "0", "false"}


def _clip(text: str, limit: int) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _key_arg(tool: str, args: dict) -> str:
    if tool == "mac_applescript":
        from server.services.hands_service import script_kind
        kind, named = script_kind(str(args.get("script") or ""))
        return f"script_kind={kind}" + (f" apps={', '.join(named[:4])}" if named else "")
    if tool.startswith(_HANDS):                     # on-screen labels and typed text are never kept
        app = args.get("app")
        key = "app" if isinstance(app, str) and app.strip() else "name"
        value = args.get(key)
        return f"{key}={_clip(value, 60)}" if isinstance(value, str) and value.strip() else ""
    if tool == "run_command" and isinstance(args.get("command"), str):
        return f"command={_clip(args['command'], _COMMAND_CHARS)}"
    for key in _KEY_ARGS:
        if isinstance(args.get(key), str) and args[key].strip():
            return f"{key}={_clip(args[key], _ARG_CHARS)}"
    return ""


def _outcome(tool: str, result: dict) -> str:
    if not result.get("ok", True):
        return "failed: " + _clip(result.get("code") or result.get("error") or "error", 80)
    exit_code = f" (exit {result['exit_code']})" if isinstance(result.get("exit_code"), int) else ""
    saved = result.get("full_output_path")
    if saved:
        return f"ok{exit_code}, full output saved to {saved}"
    if tool in _RESULT_TOOLS:
        for key in ("entries", "results", "matches", "files"):
            if result.get(key):
                return _clip(json.dumps(result[key], ensure_ascii=False, default=str), _RESULT_CHARS)
    return f"ok{exit_code}"


def _line(call: dict) -> str:
    from server.orchestrator.untrusted import counts_as_external
    tool = str(call.get("tool") or "?")
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    result = call.get("result") if isinstance(call.get("result"), dict) else {}
    key = _key_arg(tool, args)
    head = f"- {tool}" + (f" {key}" if key else "")
    if result.get("ok", True) and (result.get("external") is True or counts_as_external(tool, args)):
        return head + ": external content, source only"
    return f"{head}: {_outcome(tool, result)}"


def block(tool_trace: list[dict] | None) -> str:
    """The block for one turn ("" without tool calls or with the switch off)."""
    calls = [call for call in tool_trace or [] if isinstance(call, dict)]
    if not calls or not enabled():
        return ""
    lines = [_line(call) for call in calls[:MAX_LINES]]
    if len(calls) > MAX_LINES:
        lines.append(f"- … {len(calls) - MAX_LINES} more tool calls")
    return "\n".join([OPEN, *lines, CLOSE])
