"""Opt-in, reproducible policy comparison; generated shell text is never executed.

Set ARSLAN_FOLDER_BASELINE to a locally available commit. Only git show reads the
two baseline modules; no fetch or checkout is needed. The historical 4,810-input
corpus is absent, so this matrix reports its replacement cohorts explicitly.
"""
from __future__ import annotations

from collections import Counter
from itertools import product
import json
import os
from pathlib import Path
import posixpath
import re
import subprocess
import sys
import types

import pytest

from server.services import shell_grammar, terminal_policy as tp
from tests.server import test_s2a3_folder_tracking as folders, test_terminal_policy as policy_cases
from tests.server.test_s2a3_folder_tracking import stand_in_rules  # noqa: F401


@pytest.fixture
def baseline_policy(monkeypatch):
    revision = os.environ.get("ARSLAN_FOLDER_BASELINE")
    if not revision:
        pytest.skip("set ARSLAN_FOLDER_BASELINE to a local baseline commit")
    assert re.fullmatch(r"[0-9a-f]{40}", revision), "use a full, immutable commit ID"
    root = Path(__file__).resolve().parents[2]
    modules = {}
    for name in ("shell_text", "terminal_policy"):
        source = subprocess.run(
            ["git", "show", f"{revision}:server/services/{name}.py"],
            cwd=root, check=True, capture_output=True, text=True,
        ).stdout
        module = types.ModuleType(f"_folder_baseline_{name}")
        monkeypatch.setitem(sys.modules, module.__name__, module)
        if name == "terminal_policy":
            imported = "from server.services import shell_text"
            assert source.count(imported) == 1
            source = source.replace(imported, "")
            module.shell_text = modules["shell_text"]
        exec(compile(source, f"{revision}/{name}.py", "exec"), module.__dict__)
        modules[name] = module
    return modules["terminal_policy"]


def _parameters(module):
    """Reuse the actual parametrized inputs, including explicit pytest.param IDs."""
    texts = set()
    for name, function in vars(module).items():
        if not name.startswith("test_"):
            continue
        for mark in getattr(function, "pytestmark", ()):
            if mark.name != "parametrize":
                continue
            names = [n.strip() for n in mark.args[0].split(",")]
            field = next((n for n in ("text", "command") if n in names), None)
            if field is None:
                continue
            for row in mark.args[1]:
                values = row.values if hasattr(row, "values") else (row,) if len(names) == 1 else row
                text = values[names.index(field)]
                if isinstance(text, str):
                    texts.add(text)
    return texts


def _chains():
    endpoints = (
        f"{folders.DEL} zz-file", f"{folders.PUT} {folders.GUARDED}/zz-file",
        f"{folders.TOOL} <> {folders.GUARDED}/zz-file",
    )
    generated, folded = set(), set()
    targets = (folders.A, f"{folders.A}/{folders.B}", "..", ".")
    for length in range(1, 5):
        for steps in product(targets, repeat=length):
            # Independent oracle: normalize the complete relative path, not the reader's result.
            final = posixpath.normpath("/".join(steps))
            stays_inside = final != ".." and not final.startswith("../")
            for end in endpoints:
                text = " && ".join([*(f"cd {s}" for s in steps), end])
                generated.add(text)
                if ".." in steps and stays_inside:
                    folded.add(text)
    for first, second, join, end in product(
        (folders.A, "..", "~", f"~/{folders.GUARDED}"),
        (folders.B, "..", "~"), ("; ", " && ", " || "), endpoints,
    ):
        generated.add(f"cd {first}{join}cd {second} && {end}")
    return generated, folded


def _differential(chains):
    return {
        chain.replace("{a}", folders.A).replace("{b}", folders.B).replace("{m}", folders.MISSING)
        .replace("{p}", end)
        for chain in chains
        for end in (f"{folders.TOOL}", f"{folders.DEL} zz-file",
                    f"{folders.PUT} {folders.GUARDED}/zz-file",
                    f"{folders.TOOL} > {folders.GUARDED}/zz-file")
    }


def _compare(texts, baseline, cwd):
    counts = Counter({key: 0 for key in (
        "strings", "unchanged", "run_to_ask", "run_to_not_understood", "run_to_forbid",
        "ask_forbid_changes", "wrong_direction", "rule_changes", "reader_not_understood",
    )})
    transitions = Counter()
    for text in sorted(texts):
        before, after = baseline.assess(text), tp.assess(text, cwd=cwd)
        counts["strings"] += 1
        transitions[f"{before.level}->{after.level}"] += 1
        counts["reader_not_understood"] += not shell_grammar.read(text).understood
        if (before.level, before.rule) == (after.level, after.rule):
            counts["unchanged"] += 1
        elif before.level == "run":
            destination = "not_understood" if after.rule == tp.UNREADABLE else after.level
            counts[f"run_to_{destination}"] += 1
        else:
            counts["ask_forbid_changes"] += 1
            counts["rule_changes"] += before.level == after.level
        ranks = {"run": 0, "ask": 1, "forbid": 2}
        counts["wrong_direction"] += ranks[after.level] < ranks[before.level]
        assert ranks[after.level] >= ranks[before.level], (text, before, after)
        if before.level != "run":
            assert (before.level, before.rule) == (after.level, after.rule), (text, before, after)
    return dict(counts), dict(sorted(transitions.items()))


def make_plain_tree(texts, work):
    """Materialize the matrix's explicitly link-free work-relative assumption."""
    for text in texts:
        reading = shell_grammar.read(text)
        for possibilities in reading.folders:
            for folder in possibilities:
                if folder and not folder.startswith(("/", "~")) and ".." not in folder.split("/"):
                    (work / folder).mkdir(parents=True, exist_ok=True)


def test_policy_matrix(baseline_policy, tmp_path):
    generated, folded = _chains()
    cohorts = {
        "existing_policy": _parameters(policy_cases),
        "existing_folder": _parameters(folders),
        "generated_chains": generated,
        "differential_original": _differential(folders._CHAINS[:19]),
        "differential_added": _differential(folders._CHAINS[19:]),
    }
    make_plain_tree(set.union(*cohorts.values()), tmp_path)
    report = {name: _compare(texts, baseline_policy, tmp_path) for name, texts in cohorts.items()}
    report["total_unique"] = _compare(set.union(*cohorts.values()), baseline_policy, tmp_path)
    report["fold_inside"] = _compare(folded, baseline_policy, tmp_path)
    assert report["fold_inside"][0]["unchanged"] == len(folded)
    # Include the intervening-command shape used by the new real-bash case.
    text = f"cd {folders.A} && {folders.TOOL} && cd .. && {folders.DEL} zz-file"
    assert tp.assess(text).level == baseline_policy.assess(text).level == "run"
    print("FOLDER_MATRIX " + json.dumps(report, sort_keys=True))
