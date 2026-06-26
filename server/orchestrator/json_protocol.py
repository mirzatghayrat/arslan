"""Shared JSON rescue-parser used by security-relevant dispatch paths.

Both the router (stage-1 action dispatch) and the spawn_loop (tool/escalate
dispatch) rely on this helper.  Centralised here so that any change to the
fence-stripping or rescue heuristic is visible in one place and tested
directly.
"""
from __future__ import annotations

import json
from typing import Any


def _loads_or_none(s: str) -> Any:
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None


def parse_json_object(content: str) -> dict | None:
    """Parse a JSON object out of *content*, returning a dict or None.

    Handles two common model quirks:
    - ```json ... ``` fenced blocks (fence is stripped before parsing).
    - Commentary-wrapped JSON, e.g. 'Sure! {"tool":"x"} now.' — the object
      is rescued via a find-first-{/find-last-} slice.

    Returns None for non-dict JSON (arrays, scalars) and for unparseable input.

    Security note: this function is on the critical dispatch path for both
    the router (action selection) and the spawn_loop (tool/escalate gating).
    Any loosening of the rescue heuristic must be reviewed for injection risk.
    """
    text = (content or "").strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    text = text.strip()
    obj = _loads_or_none(text)
    if obj is None and "{" in text and "}" in text:
        # Weak models often wrap the JSON in commentary; rescue the object.
        obj = _loads_or_none(text[text.find("{") : text.rfind("}") + 1])
    return obj if isinstance(obj, dict) else None


def first_json_object(content: str) -> dict | None:
    """Return the FIRST complete, balanced ``{...}`` object as a dict, or None.

    Unlike parse_json_object's find-first/rfind-last rescue (which spans EVERYTHING
    between the outermost braces), this walks brace depth (string-aware) and stops at
    the first balanced object. That correctly handles a model emitting prose + several
    objects, e.g. '好，我去搜{"tool":"a"}{"tool":"b"}' → returns the first tool call,
    so the tool loop fires it (and can issue the next on a later step) instead of
    seeing two-objects-as-one, failing to parse, and falling through to a leaky final.
    """
    text = content or ""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                obj = _loads_or_none(text[start : i + 1])
                return obj if isinstance(obj, dict) else None
    return None
