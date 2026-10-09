"""What changed in a window since the model's last look at it (Hands v2, spec 2026-10-08-0157
§4.1 and §15 A8). agent-desktop has no diff, and its refs are new every snapshot, so elements
are matched by role + name + the path of roles and names above them. Pure functions plus a
small in-memory store; nothing is written anywhere.
"""
from __future__ import annotations

from collections import OrderedDict

MAX_WINDOWS = 64          # remembered looks (job or conversation, app, window); oldest dropped
MAX_SHOWN = 12            # changes listed; the rest are counted

Key = tuple[str, str, str]                 # (scope, app, window)
Element = tuple[str, str, str]             # (path, role, name)

_last: "OrderedDict[Key, dict[Element, str]]" = OrderedDict()


def elements(tree: dict) -> dict[Element, str]:
    """Every element of a look's tree that has a role, by (path, role, name) → its value.
    Same-named siblings get an index so they stay distinct."""
    found: dict[Element, str] = {}

    def walk(node: dict, path: str) -> None:
        role, name = str(node.get("role") or ""), str(node.get("name") or "")
        key = (path, role, name)
        n = 1
        while key in found:
            n += 1
            key = (path, role, f"{name}#{n}")
        if role:
            value = "" if "secure" in (node.get("states") or []) else str(node.get("value") or "")
            found[key] = value
        below = f"{path}/{role}:{name}"
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child, below)

    if isinstance(tree, dict):
        walk(tree, "")
    return found


def _label(element: Element) -> str:
    _, role, name = element
    name = name.split("#")[0]
    return f"{role} “{name[:60]}”" if name else role


def describe(before: dict[Element, str], after: dict[Element, str]) -> str:
    """One line: "+ added; − removed; <element> is now “value”", or "" when nothing changed."""
    changes = [f"+ {_label(e)}" for e in after if e not in before]
    changes += [f"− {_label(e)}" for e in before if e not in after]
    for element, value in after.items():
        if element in before and before[element] != value:
            shown = value.replace("\n", "⏎")
            changes.append(f"{_label(element)} is now “{shown[:80]}{'…' if len(shown) > 80 else ''}”")
    if not changes:
        return ""
    more = len(changes) - MAX_SHOWN
    line = "; ".join(changes[:MAX_SHOWN])
    return line + (f"; and {more} more" if more > 0 else "")


def since_last(scope: str, app: str, window: str, tree: dict) -> str | None:
    """The change line against this window's previous look in this scope, and remember this
    look. None for the first look (nothing to compare); "" when nothing changed."""
    key = (scope, app, window)
    now = elements(tree)
    before = _last.pop(key, None)
    _last[key] = now
    while len(_last) > MAX_WINDOWS:
        _last.popitem(last=False)
    return None if before is None else describe(before, now)


def forget(scope: str) -> None:
    for key in [k for k in _last if k[0] == scope]:
        del _last[key]
