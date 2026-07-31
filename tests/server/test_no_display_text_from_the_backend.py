"""The API must not ship display text. Stable keys only.

WHY THIS EXISTS: the second brain's navigation showed 材料 / 心得 / 画像 / 笔记
to a user whose interface was set to English, and it did so for months. The
frontend has a no-hardcoded-CJK guard that was driven to zero in S4.2-d — but it
scans web/src, and those strings were born in server/api/brain.py. A guard that
cannot see where the string comes from cannot catch it, and the whole class was
invisible to the one check that existed.

The rule: an API response carries KEYS; the interface turns them into words,
where the user's language is known. This is not stylistic — the backend has no
idea what language the person in front of the app reads.

WHAT IS NOT COVERED, so nobody mistakes the scope: this catches CJK, because
that is the alphabet our display leaks have actually been written in. English
display text in an API response is the same defect and this will not see it.
Naming it here beats a green test that implies more than it checks.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

API_DIR = pathlib.Path(__file__).resolve().parents[2] / "server" / "api"
CJK = "一-鿿぀-ヿ가-힯"

# Modules whose CJK string literals are NOT display text. Each entry needs a
# reason: an allowlist without one becomes the place bugs are parked.
#
# 🔴 EVERY ENTRY IS A KNOWN DEBT, NOT AN EXEMPTION.
#
# This guard found four modules on its first run. Three of them —
# conversations.py, runs.py, scheduled_tasks.py — were gate item ① and are now
# CLEARED: they ship keys and parameters, and the interface composes the
# sentence. They came out of this list rather than the list being widened,
# which was the stated completion criterion.
#
# registry.py remains, and its reason is a placement decision rather than a
# deferral: the unsandboxed-python warning is operator-facing, and the user put
# it outside the launch gate on purpose.
ALLOWED: dict[str, str] = {
    "registry.py": (
        "the run_python unsandboxed warning — operator-facing, shown on the "
        "capability page when the escape valve is open. Placed OUTSIDE the "
        "launch gate deliberately: it is not user-facing copy."),
}


def _string_literals(path: pathlib.Path):
    """Every string CONSTANT in the module, with its line. Docstrings and
    comments are excluded by construction: ast drops comments, and a docstring
    is an Expr statement we skip."""
    tree = ast.parse(path.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in docstrings:
                continue
            yield node.lineno, node.value


def _cjk_literals(path: pathlib.Path):
    import re

    pattern = re.compile(f"[{CJK}]")
    return [(line, text) for line, text in _string_literals(path) if pattern.search(text)]


API_FILES = sorted(p for p in API_DIR.glob("*.py") if p.name != "__init__.py")


def test_there_are_api_modules_to_scan():
    """(0) pre-assertion: a glob that matched nothing would make every test
    below vacuously true — the same shape as having no guard at all."""
    assert len(API_FILES) >= 10, f"only found {len(API_FILES)} api modules"


@pytest.mark.parametrize("path", API_FILES, ids=lambda p: p.name)
def test_no_api_module_ships_display_text(path):
    offenders = _cjk_literals(path)
    if path.name in ALLOWED:
        pytest.skip(f"allowlisted: {ALLOWED[path.name]}")
    assert not offenders, (
        f"{path.name} contains display text that the interface cannot translate:\n"
        + "\n".join(f"  line {line}: {text!r}" for line, text in offenders)
        + "\n\nShip a stable key and translate it in web/src — the backend does "
          "not know what language the user reads.")


def test_the_scanner_would_actually_find_something():
    """Discriminating: proves the reader sees literals rather than returning
    empty for every file, which would make the guard above unfalsifiable."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write('"""A docstring with 中文 in it, which must NOT count."""\n')
        fh.write('LABEL = "材料"\n')
        fh.write('# a comment with 中文, also not counted\n')
        probe = pathlib.Path(fh.name)

    found = _cjk_literals(probe)
    probe.unlink()
    assert [text for _, text in found] == ["材料"], (
        f"the scanner should find exactly the literal, got {found}")


def test_the_allowlist_entries_still_exist_and_are_justified():
    """An allowlist that outlives its files stops being a list of known debts
    and starts being noise."""
    for name, reason in ALLOWED.items():
        assert (API_DIR / name).is_file(), f"{name} is allowlisted but gone"
        assert reason.strip(), f"{name} is allowlisted with no reason"
