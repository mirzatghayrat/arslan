"""Specific alternatives at the moment a tool fails (0.1.50 P2, design 1.3).

A system-prompt rule ("when a tool fails, try another route") did not change
behaviour in the kernel bench: on T1 Arslan handed back after AppleScript was
refused, while Hermes switched to EventKit every time. What works is naming
the alternative where the failure happens. This table maps known failure
signatures to concrete routes; the hint is trusted host text appended after
the untrusted result frame, never inside it.
"""
from __future__ import annotations

import re

_HINTS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"-1743\b|-10004\b|not authori[sz]ed to send apple events|privilege violation", re.I),
     "macOS refused AppleScript automation for this app. Other routes, in order: a Swift script that uses "
     "EventKit for Reminders or Calendar (write it to a .swift file and run `swift file.swift`; it uses a "
     "different permission), a Shortcut (mac_list_shortcuts / mac_run_shortcut), or ask the user to allow "
     "Automation for Arslan in System Settings. Do not retry the same AppleScript."),
    (re.compile(r"command not found|no such file or directory: ?[\w./-]+$", re.I | re.M),
     "That command is not installed. Use an installed alternative, or a short python3 or swift script; "
     "installing software shows the user the command first."),
    (re.compile(r"permission denied|operation not permitted|read-only file system", re.I),
     "The system refused that location. Save inside the workspace folder (it is writable), or explain "
     "exactly which path was refused."),
)

_WEB_EMPTY = ("That page gave no readable text (it may need scripts). Try browser_open for script-rendered "
              "pages, or another source from your search results.")
_WEB_BLOCKED = "That site refused the request. Use another source; do not retry this URL."


def hint_for(tool_key: str, result: dict) -> str | None:
    """A trusted recovery hint for a failed tool result, or None."""
    if result.get("ok"):
        return None
    text = " ".join(str(result.get(k) or "") for k in ("error", "stderr", "stdout", "summary"))
    if tool_key == "web_extract":
        if re.search(r"no extractable text|empty|javascript", text, re.I):
            return _WEB_EMPTY
        if re.search(r"\b(401|403|429|451)\b|blocked|forbidden|rejected|paywall", text, re.I):
            return _WEB_BLOCKED
        return None
    for pattern, hint in _HINTS:
        if pattern.search(text):
            return hint
    return None
