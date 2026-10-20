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
import re

OPEN, CLOSE = "<turn_tools>", "</turn_tools>"
_RESULT_CHARS = 500
_ARG_CHARS = 160
_COMMAND_CHARS = 80
# Bounds one turn's block (about 3.5k estimated tokens at most): a long tool run must not eat the
# next turns' history budget. The rest is counted, not listed.
MAX_LINES = 20
BLOCK_TOKENS = 800             # and by estimated tokens: CJK lines are dense (③Hands' review)
# Result TEXT is kept only for these: their output is the user's own file names. Every other tool is
# recorded by its outcome. An allowlist, not a blocklist (③Hands' review of K2a): untrusted's fixed
# list has no Mac or Hands tool, so window text, AppleScript and Shortcut output, and command or
# code output would otherwise have been persisted as something Arslan said.
_RESULT_TOOLS = frozenset({"list_dir", "search_files"})
# Arguments recorded: identifiers, never bodies (a script, code, text typed or written, a label).
_KEY_ARGS = ("path", "url", "query", "name", "title")
_HANDS = ("desktop_", "mac_")
# Their query is often the user's own memory or need ("user's diagnosis: …"): stored here it would be
# replayed to a cloud model later, past the memory gate (③Hands' review). Not recorded.
_PRIVATE_QUERY = frozenset({"recall", "conversation_search", "search_files", "web_search"})


def enabled() -> bool:
    """The switch back for v0.1.63. Deleted in v0.1.64 if v0.1.63 has been installed 7 days
    without needing it and M3 #3 and #11 pass (K2 card)."""
    return os.environ.get("ARSLAN_TURN_TOOL_SUMMARY", "").lower() not in {"off", "0", "false"}


def _clip(text: str, limit: int) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _arg(key: str, value: str, limit: int) -> str:
    """One persisted argument; a value carrying a credential is omitted (③Hands' review: a command's
    first characters can hold a token). content_policy is a screen, not a guarantee."""
    from arslan.companion.content_policy import contains_credential
    return f"{key}=<credential omitted>" if contains_credential(value) else f"{key}={_clip(value, limit)}"


def _key_arg(tool: str, args: dict) -> str:
    if tool == "mac_applescript":
        from server.services.hands_service import script_kind
        kind, named = script_kind(str(args.get("script") or ""))
        return f"script_kind={kind}" + (f" apps={', '.join(named[:4])}" if named else "")
    if tool.startswith(_HANDS):                     # on-screen labels and typed text are never kept
        app = args.get("app")
        key = "app" if isinstance(app, str) and app.strip() else "name"
        value = args.get(key)
        return _arg(key, value, 60) if isinstance(value, str) and value.strip() else ""
    if tool == "run_command" and isinstance(args.get("command"), str):
        return _arg("command", args["command"], _COMMAND_CHARS)
    for key in _KEY_ARGS:
        if key == "query" and tool in _PRIVATE_QUERY:
            continue
        if isinstance(args.get(key), str) and args[key].strip():
            return _arg(key, args[key], _ARG_CHARS)
    return ""


def _outcome(tool: str, result: dict) -> str:
    if not result.get("ok", True):
        from arslan.companion.content_policy import contains_credential
        if tool in ("run_python", "run_command"):   # their error carries the stderr tail (③Hands' review)
            error = str(result.get("error") or "")
            exit_text = re.match(r"exit (-?\d+)", error)
            code = result.get("exit_code") if isinstance(result.get("exit_code"), int) else (
                int(exit_text.group(1)) if exit_text else None)
            # The executors' own timeout wording (code_sandbox, ssh_exec), at the start: stderr comes after "exit N".
            timed_out = re.match(r"(execution )?timed out after \d+s", error) is not None
            return "failed: " + (str(result.get("code")) if result.get("code") else
                                 f"exit {code}" if code is not None else "timed out" if timed_out else "error")
        reason = str(result.get("code") or result.get("error") or "error")
        return "failed: " + ("<credential omitted>" if contains_credential(reason) else _clip(reason, 80))
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
    if result.get("external") is True or counts_as_external(tool, args):
        if result.get("ok", True):
            return head + ": external content, source only"
        # An external tool's error text can carry the outside's words: its code only.
        return head + ": failed: " + _clip(str(result.get("code") or "error"), 80)
    return f"{head}: {_outcome(tool, result)}"


def block(tool_trace: list[dict] | None) -> str:
    """The block for one turn ("" without tool calls or with the switch off)."""
    calls = [call for call in tool_trace or [] if isinstance(call, dict)]
    if not calls or not enabled():
        return ""
    from arslan.context_budget import estimate_tokens
    lines: list[str] = []
    for call in calls[:MAX_LINES]:
        line = _line(call)
        if lines and estimate_tokens("\n".join([*lines, line])) > BLOCK_TOKENS:
            break
        lines.append(line)
    if len(calls) > len(lines):
        lines.append(f"- … {len(calls) - len(lines)} more tool calls")
    return "\n".join([OPEN, *lines, CLOSE])
