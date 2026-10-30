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
Seen = tuple[str, int | None]              # (value, how many elements a part the look left closed holds)

_last: "OrderedDict[Key, dict[Element, Seen]]" = OrderedDict()


def elements(tree: dict) -> dict[Element, Seen]:
    """Every element of a look's tree that has a role, by (path, role, name) → its value and, for a part the
    look left closed, how many elements it holds. A look is a skeleton that stops a few levels down, so a list
    that grew by a row changes only that count (FRONT1, F1 of ⓪Plan's review of #512): without it, the look
    would say nothing changed, which `_FRONT` makes a reason to borrow the front and do the action again.
    Same-named siblings get an index so they stay distinct."""
    found: dict[Element, Seen] = {}

    def walk(node: dict, path: str) -> None:
        role, name = str(node.get("role") or ""), str(node.get("name") or "")
        key = (path, role, name)
        n = 1
        while key in found:
            n += 1
            key = (path, role, f"{name}#{n}")
        if role:
            value = "" if "secure" in (node.get("states") or []) else str(node.get("value") or "")
            inside = node.get("children_count")
            closed = isinstance(inside, int) and not node.get("children")
            found[key] = (value, inside if closed else None)
        below = f"{path}/{role}:{name}"
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child, below)

    if isinstance(tree, dict):
        walk(tree, "")
    return found


def _label(element: Element) -> str:
    from server.services.hands_contract import one_line
    _, role, name = element
    name = one_line(name.split("#")[0])
    return f"{one_line(role)} “{name[:60]}”" if name else one_line(role)


def describe(before: dict[Element, Seen], after: dict[Element, Seen]) -> str:
    """One line: "+ added; − removed; <element> is now “value”; <element> now holds N (was M)", or "" when
    nothing changed."""
    from server.services.hands_contract import one_line
    changes = [f"+ {_label(e)}" for e in after if e not in before]
    changes += [f"− {_label(e)}" for e in before if e not in after]
    for element, (value, inside) in after.items():
        if element not in before:
            continue
        was_value, was_inside = before[element]
        if was_value != value:
            shown = one_line(value)
            changes.append(f"{_label(element)} is now “{shown[:80]}{'…' if len(shown) > 80 else ''}”")
        if inside is not None and was_inside is not None and inside != was_inside:
            changes.append(f"{_label(element)} now holds {inside} (was {was_inside})")
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
