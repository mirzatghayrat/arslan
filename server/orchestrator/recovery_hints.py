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
# web_extract says "url refused: <label>" when Arslan's OWN network guard (net_pin) refused the
# address. It is never the site's refusal: "blocked address (local network)" matched the pattern
# above and was answered "That site refused the request" (0.1.61 final review).
_WEB_GUARD_PREFIX = "url refused:"
_WEB_GUARD_HTTPS_ONLY_LABEL = "behind fake-IP DNS only https:// on port 443 is fetched"
_WEB_GUARD_HTTPS_ONLY = ("Arslan's own network guard refused this address, not the site. Retry once "
                         "with the https:// form of the same page if it has one; otherwise use "
                         "another source.")
_WEB_GUARD_REFUSED = ("Arslan's own network guard refused this address (it is on the local network "
                      "or not a valid public host). Don't retry it; use another source.")
# web_extract says "fetch failed: the site refused (http 403)" when the SITE answered 401, 403 or
# 451 to a page read (it used to say "key-rejected", a search API key's word). The generic
# site-refusal pattern in `hint_for` matches that text too, since the number is in it, and would
# answer "That site refused the request": the branch for this label has to come before it. The
# label is the executor's own, so it is matched at the start of the error and nowhere else. The
# hint follows the code, because the remedy does: a 403 blocks automated reading, a 401 wants a
# sign-in Arslan does not have, a 451 is a legal block. Any other code in that shape (none is
# produced today) gets the 403 sentence.
_WEB_SITE_REFUSED_LABEL = re.compile(r"fetch failed: the site refused \(http (\d{3})\)")
_WEB_SITE_REFUSED = ("This site blocks automated reading. Don't retry this URL; use another "
                     "source, or browser_open if the page is essential.")
_WEB_SITE_REFUSED_BY_CODE = {
    401: "This page needs a sign-in Arslan doesn't have; use another source.",
    451: "This page is unavailable for legal reasons here; use another source.",
}


def hint_for(tool_key: str, result: dict) -> str | None:
    """A trusted recovery hint for a failed tool result, or None."""
    if result.get("ok"):
        return None
    text = " ".join(str(result.get(k) or "") for k in ("error", "stderr", "stdout", "summary"))
    if tool_key == "web_extract":
        error = str(result.get("error") or "")
        if error.startswith(_WEB_GUARD_PREFIX):
            # Checked first: the guard's labels must never reach the site-refusal pattern. Any
            # label but the https-only one (an unknown one included) means "do not retry".
            label = error[len(_WEB_GUARD_PREFIX):].strip()
            return _WEB_GUARD_HTTPS_ONLY if label == _WEB_GUARD_HTTPS_ONLY_LABEL else _WEB_GUARD_REFUSED
        refused = _WEB_SITE_REFUSED_LABEL.match(error)
        if refused:
            # Before the generic pattern below, which would call it "That site refused the request".
            return _WEB_SITE_REFUSED_BY_CODE.get(int(refused.group(1)), _WEB_SITE_REFUSED)
        if re.search(r"no extractable text|empty|javascript", text, re.I):
            return _WEB_EMPTY
        if re.search(r"\b(401|403|429|451)\b|blocked|forbidden|rejected|paywall", text, re.I):
            return _WEB_BLOCKED
        return None
    for pattern, hint in _HINTS:
        if pattern.search(text):
            return hint
    return None
