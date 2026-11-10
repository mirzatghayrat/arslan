"""HR-0: the cases existing tests already give each rule, read from their own parametrize marks (no command text is
written again here), and the pytest collection the registry's test ids are checked against."""
from __future__ import annotations

import functools
import importlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def function_of(node_id: str):
    """The test function a node id names (its parameters, if any, left out)."""
    path, name = node_id.split("[", 1)[0].split("::")
    module = importlib.import_module(path.removesuffix(".py").replace("/", "."))
    return getattr(module, name)


def cases(node_id: str) -> list[dict]:
    """Each case of a parametrized test, as {argname: value}; [] for a test with no parametrize mark."""
    rows: list[dict] = []
    for mark in getattr(function_of(node_id), "pytestmark", []):
        if mark.name != "parametrize":
            continue
        names, values = mark.args[0], mark.args[1]
        names = [n.strip() for n in names.split(",")] if isinstance(names, str) else list(names)
        for value in values:
            value = getattr(value, "values", value)            # pytest.param(...)
            rows.append(dict(zip(names, value if len(names) > 1 else (value,))))
    return rows


def first_command(node_id: str, rule: str | None = None) -> str:
    """The first command an existing test gives `rule` (or its first command, when it names no rule)."""
    return next(c["command"] for c in cases(node_id) if rule is None or c.get("rule") == rule)


@functools.cache
def collected(files: tuple[str, ...]) -> frozenset[str]:
    """Every node id pytest collects from `files`, by pytest's own collection (never by reading the files)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                          "-o", "addopts=", *files], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    found = frozenset(line.strip() for line in out.stdout.splitlines() if "::" in line)
    assert found, out.stdout[-2000:] + out.stderr[-2000:]
    return found


def unresolved(rows, ids: frozenset[str]) -> list[str]:
    """The rows whose test is not a collected node id, nor the function of collected parametrized ones."""
    functions = {node_id.split("[", 1)[0] for node_id in ids}
    return [r.id for r in rows if r.test not in ids and r.test not in functions]
