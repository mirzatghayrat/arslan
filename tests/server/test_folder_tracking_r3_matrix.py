"""Local-object delta comparison with each revision's own text, grammar and policy."""
from collections import Counter
from itertools import product
import json
from pathlib import Path
import re
import subprocess
import sys
import types

from server.services import terminal_policy as tp
from tests.server import test_folder_tracking_matrix as matrix
from tests.server import test_s2a3_folder_tracking as folders
from tests.server.test_s2a3_folder_tracking import stand_in_rules  # noqa: F401

ROUND_FOUR = "d0057b2fa2f0c674996d0148424007f670136c95"
ROUND_THREE = "be8c1393cb2be8aacfbd960b1496d2a1da02f05f"
ROUND_TWO = "1925e15895f675027e496d15d82a05d221065169"
MAINS = (
    "c6647eb915249d77d84e8a243dacf03eb931044c",
)


def load_revision(revision, monkeypatch):
    """Do not use the main-only matrix fixture for a folder-tracking revision."""
    modules = {}
    names = ("shell_grammar", "shell_text", "terminal_policy") if revision in (ROUND_TWO, ROUND_THREE, ROUND_FOUR) else ("shell_text", "terminal_policy")
    for name in names:
        source = subprocess.run(
            ["git", "show", f"{revision}:server/services/{name}.py"],
            cwd=Path(__file__).resolve().parents[2], check=True, capture_output=True, text=True,
        ).stdout
        module = types.ModuleType(f"_r3_{revision}_{name}")
        monkeypatch.setitem(sys.modules, module.__name__, module)
        if name == "terminal_policy":
            source, count = re.subn(r"^from server.services import (?:shell_grammar, )?shell_text$", "", source,
                                    flags=re.M)
            assert count == 1
            module.__dict__.update(modules)
        exec(compile(source, f"{revision}/{name}.py", "exec"), module.__dict__)
        modules[name] = module
    policy = modules["terminal_policy"]
    for name in ("_MOVED_DELETERS", "_MOVED_WRITERS", "_MOVED_FINDERS", "_PROTECTED_PATH_C"):
        setattr(policy, name, getattr(tp, name))
    return policy


def repository_corpus():
    return (matrix._parameters(matrix.policy_cases) | matrix._parameters(folders)
            | matrix._chains()[0] | matrix._differential(folders._CHAINS))


def structural_corpus():
    # Explicit regeneration of the reviewed corpus class; its original fourteen targets were not supplied.
    targets = (folders.A, f"{folders.A}/{folders.B}", ".", "..", "~", f"~/{folders.A}",
               f"~/{folders.A}/{folders.B}", f"~/{folders.A}/..", "~/..",
               f"~//{folders.A}/../..", f"~///{folders.A}/../..",
               f"/{folders.A}", f"/{folders.A}/{folders.B}", f"/{folders.A}/..")
    endpoints = (f"{folders.DEL} zz-file", f"{folders.PUT} {folders.GUARDED}/zz-file",
                 f"{folders.TOOL} <> {folders.GUARDED}/zz-file", folders.TOOL)
    return {" && ".join([*(f"cd {step}" for step in steps), endpoint])
            for length in range(1, 4) for steps in product(targets, repeat=length) for endpoint in endpoints}


def transitions(texts, baseline, cwd):
    counts = Counter()
    for text in sorted(texts):
        before, after = baseline.assess(text), tp.assess(text, cwd=cwd)
        counts[f"{before.level}->{after.level}"] += 1
    return dict(sorted(counts.items()))


def test_revision_comparisons(tmp_path, monkeypatch):
    corpora = {"repository": repository_corpus(), "structural": structural_corpus()}
    assert len(corpora["structural"]) == 11816
    matrix.make_plain_tree(set.union(*corpora.values()), tmp_path)
    report = {}
    for revision in (*MAINS, ROUND_TWO):
        baseline = load_revision(revision, monkeypatch)
        report[revision] = {name: transitions(texts, baseline, tmp_path) for name, texts in corpora.items()}
        if revision == ROUND_TWO:
            report[revision]["repository_unknown_work"] = transitions(corpora["repository"], baseline, None)
        if revision in MAINS:
            for counts in report[revision].values():
                assert not any(count and change in ("ask->run", "forbid->run", "forbid->ask")
                               for change, count in counts.items())
    # Isolate the separator-parent class from topology changes.
    from tests.server.test_folder_tracking_r3 import stack_oracle
    baseline = load_revision(ROUND_TWO, monkeypatch)
    fixes = excess = wrong_folders = 0
    for text in corpora["structural"]:
        before, after = baseline.assess(text), tp.assess(text, cwd=tmp_path)
        fixes += before.level == "ask" and after.level == "run"
        reading = tp.shell_grammar.read(text)
        path = ""
        for words in reading.commands[:-1]:
            target = words[1]
            path = stack_oracle(target if target.startswith(("/", "~")) or not path else path + "/" + target)
        wrong_folders += reading.folders[-1] != (path,)
        end = reading.commands[-1]
        if end[0] == folders.DEL:
            expected = "ask" if path.startswith(("/", "~")) or ".." in path.split("/") else "run"
        elif end[0] == folders.PUT or reading.writes:
            destination = stack_oracle(path + "/" + folders.GUARDED + "/zz-file") if path else folders.GUARDED
            expected = "ask" if destination.startswith("~/" + folders.GUARDED + "/") else "run"
        else:
            expected = "run"
        excess += expected == "run" and after.level == "ask"
        assert after.level == expected, (text, path, after, expected)
    assert fixes > 0 and excess == wrong_folders == 0
    report["separator_asks_removed"] = fixes
    report["separator_excess_remaining"] = excess
    report["wrong_folders"] = wrong_folders
    print("R3_MATRIX " + json.dumps(report, sort_keys=True))


def test_topology_delta(tmp_path, monkeypatch):
    baseline = load_revision(ROUND_TWO, monkeypatch)
    mains = [load_revision(revision, monkeypatch) for revision in MAINS]
    report = {}
    for topology in ("plain", "outside-link", "inside-link", "deep-link", "missing"):
        work = tmp_path / topology
        work.mkdir()
        outside = tmp_path / (topology + "-outside")
        (outside / folders.B).mkdir(parents=True)
        prefix = folders.A
        if topology == "plain":
            (work / prefix / folders.B).mkdir(parents=True)
        elif topology == "outside-link":
            (work / prefix).symlink_to(outside, target_is_directory=True)
        elif topology == "inside-link":
            (work / "zz-real" / folders.B).mkdir(parents=True)
            (work / prefix).symlink_to(work / "zz-real", target_is_directory=True)
        elif topology == "deep-link":
            (work / prefix).mkdir()
            (work / prefix / "zz-link").symlink_to(outside, target_is_directory=True)
            prefix += "/zz-link"
        texts = {f"{move} {prefix}/{folders.B} && {parent} {up} && {end}"
                 for move, parent, up, end in product(
                     ("cd", "pushd"), ("cd", "pushd"), ("..", "../.", "../"),
                     (f"{folders.DEL} zz-file", f"{folders.FIND} zz-file -delete"))}
        report[topology] = transitions(texts, baseline, work)
        assert report[topology] == {"run->run" if topology == "plain" else "run->ask": 24}
        for main in mains:
            cumulative = transitions(texts, main, work)
            assert cumulative == report[topology]
    print("R3_TOPOLOGY " + json.dumps(report, sort_keys=True))


def test_redundant_home_parent_class(monkeypatch):
    baseline = load_revision(ROUND_TWO, monkeypatch)
    texts = {f"cd ~{separator}{suffix} && {end}"
             for separator, suffix, end in product(
                 ("//", "///"),
                 (f"{folders.A}/../..", f"{folders.A}/{folders.B}/../../..", f"../{folders.A}/.."),
                 (f"{folders.PUT} {folders.GUARDED}/zz-file", f"{folders.TOOL} > {folders.GUARDED}/zz-file",
                  f"{folders.TOOL} <> {folders.GUARDED}/zz-file"))}
    assert len(texts) == 18
    for text in texts:
        assert baseline.assess(text).level == "ask"
        assert tp.assess(text).level == "run"
