"""EXC1 (v0.1.64, card docs/plans/0164/EXC1-silent-catches.md; docs/sessions.md §12 rule 4): a broad
`except` that silently swallows says why on its own line, as `# noqa: BLE001 — <why>`.

Broad: `Exception`, `BaseException` or a bare `except`, alone or in a tuple. Silent: the body is only `pass`
(EXC1a), `continue`, or `return` of a constant (`None`, a literal, an empty list, dict, tuple or set; EXC1b).
On an execution or permission path the reason says it fails closed. Ruff's BLE001 is not the tool: it would flag
all ~294 broad handlers, most of which log or re-raise. Python only; the Rust Hands helper is kept by review.
"""
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGES = ("server", "arslan")
BROAD = {"Exception", "BaseException"}
REASON = re.compile(r"#\s*noqa:\s*BLE001\s*—\s*\S")


def _broad(node: ast.expr | None) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Name):
        return node.id in BROAD
    if isinstance(node, ast.Attribute):
        return node.attr in BROAD
    if isinstance(node, ast.Tuple):
        return any(_broad(elt) for elt in node.elts)
    return False


def _silent(statement: ast.stmt) -> bool:
    if isinstance(statement, (ast.Pass, ast.Continue)):
        return True
    if not isinstance(statement, ast.Return):
        return False
    value = statement.value
    if value is None or isinstance(value, ast.Constant):
        return True
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        return not value.elts
    return isinstance(value, ast.Dict) and not value.keys


def unexplained(source: str, name: str = "<source>") -> list[str]:
    """`name:line` of every silent broad handler whose `except` line gives no reason."""
    lines = source.splitlines()
    return [f"{name}:{node.lineno}" for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ExceptHandler) and _broad(node.type)
            and len(node.body) == 1 and _silent(node.body[0])
            and not REASON.search(lines[node.lineno - 1])]


def test_every_silent_broad_catch_says_why():
    found = [hit for package in PACKAGES for path in sorted((ROOT / package).rglob("*.py"))
             for hit in unexplained(path.read_text(encoding="utf-8"), str(path.relative_to(ROOT)))]
    assert found == [], "a silent broad except needs `# noqa: BLE001 — <why>` on its line: " + ", ".join(found)


def test_the_check_tells_the_cases_apart():
    flagged = """
try:
    a()
except Exception:
    pass
try:
    a()
except:
    pass
try:
    a()
except (OSError, BaseException):  # noqa: BLE001
    pass
for x in y:
    try:
        a()
    except Exception:
        continue
def f():
    try:
        a()
    except Exception:
        return True
    try:
        a()
    except Exception:
        return {}
    try:
        a()
    except Exception:
        return
"""
    assert unexplained(flagged) == ["<source>:4", "<source>:8", "<source>:12", "<source>:17", "<source>:22",
                                    "<source>:26", "<source>:30"]
    fine = """
try:
    a()
except Exception:  # noqa: BLE001 — the window may be gone
    pass
try:
    a()
except OSError:
    pass
try:
    a()
except Exception as exc:
    log(exc)
def f():
    try:
        a()
    except Exception:
        return fallback()
    try:
        a()
    except Exception:
        return [1]
    try:
        a()
    except Exception:  # noqa: BLE001 — fails closed: unreadable means ask
        return True
"""
    assert unexplained(fine) == []
