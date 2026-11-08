"""Reproducible text-only comparison of local objects and the working tree.

Run as a Python module with --output pointing to an ignored evidence directory.
Pytest collects six stratified checks by default; QUOTED_ARGS_EVIDENCE_FULL=1
selects every generated row. Default strata keep every named rule, carrier,
operand and option class and every command position. Historical word cases are
grouped by rule/position; expanded positives by seed/position/wrapper; named
positives by seed/position; negatives by carrier/kind/position; compositions by
seed/position/tail. Select bucket number modulo bucket length, rotating spelling
and seed choices instead of always taking the first. All 336 option positives,
63 option negatives, 133 operand controls and twelve file cases run by default.
Only Git object reads are subprocesses. Generated commands are passed solely to
assess/read; no scripts, stubs or links are created or executed. The review's
unpublished generator is unavailable: this reconstructs its documented shapes,
not its exact input bytes. Counts are generated cases, including duplicates.
"""
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import shlex
import statistics
import subprocess
import sys
import time
import types

import pytest

from server.services import shell_grammar as sg, terminal_policy as tp
from tests.server.test_quoted_args_file_run import (
    FAMILIES, NAMED, OPERANDS, OPTION_NEGATIVES, OPTION_OPERATIONS, POSITIONS,
    RANK, REFUSED_TAILS, operand_text, spelled,
)
from tests.server.test_quoted_command_word import CASES, RULES, SEPARATORS, SHELL_CASES
from tests.server.shell_differential_support import FILE_SEEDS


def snapshot(revision):
    modules = []
    for basename in ("shell_grammar", "terminal_policy"):
        source = subprocess.check_output(
            ["git", "show", f"{revision}:server/services/{basename}.py"], text=True)
        name = revision + "_" + basename
        module = types.ModuleType(name)
        sys.modules[name] = module
        exec(compile(source, f"<{name}>", "exec"), module.__dict__)
        modules.append(module)
    modules[1].shell_grammar = modules[0]
    return modules


def positives():
    for i, row in enumerate([*CASES, *SHELL_CASES]):
        yield "word/" + str(i), row.values[0]
    for i, (words, _, _) in enumerate(NAMED):
        for family in FAMILIES:
            for position in POSITIONS:
                yield f"named/{i}/{family}/{position}", spelled(words, family, position)
    # Do not turn a redirection or multi-command seed into ordinary arguments.
    seeds = [(rule, tuple(shlex.split(program + rest))) for rule, _, program, rest in RULES
             if rule != tp.UNREADABLE and "&&" not in rest and "<" not in rest]
    seeds += [(rule, words) for words, _, rule in NAMED]
    for i, (rule, words) in enumerate(seeds):
        for family in FAMILIES:
            for position, before in SEPARATORS.items():
                plain = before + spelled(words, family, "plain")
                for wrap, text in (("plain", plain), ("shell", "bash -c " + shlex.quote(plain)),
                                   ("wrapper", before + "env FLAG=sample " + spelled(words, family, "plain"))):
                    yield f"expanded/{i}-{rule}/{family}/{position}/{wrap}", text


def negatives():
    seeds = [(program, program + rest) for rule, _, program, rest in RULES if rule != tp.UNREADABLE]
    seeds += [(words[0], " ".join(words)) for words, _, _ in NAMED]
    carriers = {
        "echo": lambda q: "echo " + q,
        "printf": lambda q: "printf '%s' " + q,
        "filename": lambda q: "cat -- " + q,
        "message": lambda q: "git commit -m " + q,
        "pattern": lambda q: "grep -e " + q + " notes.txt",
        "shell-data": lambda q: "bash -c " + shlex.quote("echo " + q),
        "wrapper-data": lambda q: "env FLAG=sample echo " + q,
        "launcher-data": lambda q: "xargs printf '%s' " + q,
        "heredoc": lambda q: "cat <<'END_DATA'\n" + shlex.split(q)[0] + "\nEND_DATA",
        "here-string": lambda q: "cat <<< " + q,
    }
    separators = ("\n", "; ", " && ", " || ", " | ", " & ")
    for i, seed in enumerate(seeds):
        for kind, data in zip(("program", "phrase"), seed):
            for carrier, render in carriers.items():
                for position, before in SEPARATORS.items():
                    yield f"data/{i}/{kind}/{carrier}/{position}", before + render(shlex.quote(data))
                for j, separator in enumerate(separators):
                    yield f"data/{i}/{kind}/{carrier}/inside-{j}", render(shlex.quote("prefix" + separator + data))
    for name, words, _ in OPERANDS:
        for position, before in SEPARATORS.items():
            yield f"operand/{name}/{position}", before + operand_text(words)


def compositions():
    for i, (words, _, rule) in enumerate(NAMED):
        for family in FAMILIES:
            for position in POSITIONS:
                standalone = spelled(words, family, position)
                for tail, suffix in REFUSED_TAILS.items():
                    yield f"composition/{i}-{rule}/{family}/{position}/{tail}", standalone, standalone + "; " + suffix


def option_positives():
    for name, words, _, _ in OPTION_OPERATIONS:
        for family in FAMILIES:
            for position in POSITIONS:
                yield f"{name}/{family}/{position}", spelled(words, family, position)


def option_negatives():
    for name, words in OPTION_NEGATIVES:
        for position, before in SEPARATORS.items():
            yield f"{name}/{position}", before + operand_text(words)


def file_cases():
    for seed in FILE_SEEDS:
        for family, text in (("file-script", "bash ./case.sh"), ("cwd-script", "cd child; bash case.sh"),
                             ("written-script", "printf '%s\\n' " + shlex.quote(seed.text) + " > case.sh; bash case.sh"),
                             ("link-script", "bash ./linked.sh")):
            yield family + "/" + seed.id, text


def stratified(rows):
    if os.environ.get("QUOTED_ARGS_EVIDENCE_FULL") == "1":
        return list(rows)
    buckets = defaultdict(list)
    word_cases = [*CASES, *SHELL_CASES]
    for row in rows:
        parts = row[0].split("/")
        if parts[0] == "word":
            case = word_cases[int(parts[1])]
            position = next(p for p in SEPARATORS if "-" + p + "-" in case.id)
            key = ("word", case.values[2], position)
        elif parts[0] in {"named", "expanded", "composition"}:
            key = tuple(parts[:2] + parts[3:])
        elif parts[0] == "data":
            key = tuple(parts[:1] + parts[2:])
        else:
            key = tuple(parts)
        buckets[key].append(row)
    return [bucket[i % len(bucket)] for i, bucket in enumerate(buckets.values())]


def assert_matrix(result, *, negative=False):
    assert not result["toward_run"], result["toward_run"]
    if negative:
        assert not result["changed_from_main"], result["changed_from_main"]
    else:
        regressions = {transition: count for transition, count in result["transitions"]["pr_to_fixed"].items()
                       if RANK[transition.split("->")[1]] < RANK[transition.split("->")[0]]}
        assert not regressions, regressions


@pytest.fixture(scope="module")
def evidence_versions():
    return [snapshot("3eec545b"), snapshot("9be27b5f"), (sg, tp)]


@pytest.mark.parametrize("kind", ["positive", "negative", "option-positive", "option-negative", "composition", "files"])
def test_local_object_evidence(kind, evidence_versions, record_property):
    versions = evidence_versions
    if kind == "files":
        rows = list(file_cases())
        for case, text in rows:
            reading = sg.read(text)
            assert not reading.understood and reading.why and not reading.commands and not reading.capped, case
            assert all(policy.assess(text).level == "run" for _, policy in versions), case
    elif kind == "composition":
        rows = stratified(compositions())
        for case, standalone, text in rows:
            reading = sg.read(text)
            assert not reading.understood and not reading.commands, case
            assert RANK[tp.assess(text).level] >= RANK[tp.assess(standalone).level], case
        assert_matrix(matrix(((case, text) for case, _, text in rows), versions))
    else:
        generate = {"positive": positives, "negative": negatives,
                    "option-positive": option_positives, "option-negative": option_negatives}[kind]
        rows = stratified(generate())
        # Reading is a text-only check, including intentionally refused carriers.
        for _, text in rows:
            sg.read(text)
        assert_matrix(matrix(rows, versions), negative="negative" in kind)
    record_property("generated_rows", len(rows))


def matrix(rows, versions):
    transitions = defaultdict(Counter)
    classes = defaultdict(Counter)
    changes = []
    toward_run = []
    count = 0
    for case, text in rows:
        count += 1
        levels = [policy.assess(text).level for _, policy in versions]
        for a, b, label in ((0, 1, "main_to_pr"), (0, 2, "main_to_fixed"), (1, 2, "pr_to_fixed")):
            transition = levels[a] + "->" + levels[b]
            transitions[label][transition] += 1
            classes[case.split("/")[0] + "/" + label][transition] += 1
        if levels[0] != levels[2]:
            changes.append({"id": case, "main": levels[0], "pr": levels[1], "fixed": levels[2]})
        if RANK[levels[2]] < RANK[levels[0]]:
            toward_run.append(case)
    return dict(cases=count, transitions=dict(transitions), by_class=dict(classes),
                changed_from_main=changes, toward_run=toward_run)


def clear(policy):
    for value in vars(policy).values():
        if hasattr(value, "cache_clear"):
            value.cache_clear()


def cost(versions):
    shapes = {
        "keychain-near-miss": lambda n: "security '" + ("find-generic-password " * (n // 22)) + "'",
        "git-near-miss": lambda n: "git '" + "x " * (n // 2) + "'",
        "quote-fragments": lambda n: "echo " + "'x'" * (n // 3),
        "blank-run": lambda n: "git " + " " * n + "'push'",
        "many-commands": lambda n: "true; " * (n // 6),
        "launcher-options": lambda n: "xargs " + "-n 1 " * (n // 5) + "echo",
        "escaped-words": lambda n: "echo " + "\\x " * (n // 3),
        "unterminated-quote": lambda n: "echo '" + "x" * n,
    }
    results = []
    for name, make in shapes.items():
        for size in (100, 500, 1000, 2000, 3800, 7600):
            text = make(size)
            row = {"shape": name, "size": size}
            for label, (_, policy) in zip(("main", "pr", "fixed"), versions):
                timings = []
                for _ in range(3):
                    clear(policy)
                    start = time.perf_counter()
                    policy.assess(text)
                    timings.append((time.perf_counter() - start) * 1000)
                row[label + "_median_ms"] = statistics.median(timings)
            results.append(row)
    isolated = []
    for size in (1000, 2000, 3800):
        text = shapes["keychain-near-miss"](size)
        words = sg.read(text).commands[0]
        row = {"size": size}
        old = versions[1][1]
        for label, run in (
            ("pr", lambda: [pattern.match(" ".join(words)) for _, pattern, _, masked in old._FORBID_C if not masked]),
            ("fixed", lambda: tp._named_rules(words)),
        ):
            timings = []
            for _ in range(3):
                start = time.perf_counter()
                run()
                timings.append((time.perf_counter() - start) * 1000)
            row[label + "_median_ms"] = statistics.median(timings)
        isolated.append(row)
    return {"assessment": results, "isolated_named_pass": isolated}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    versions = [snapshot("3eec545b"), snapshot("9be27b5f"), (sg, tp)]
    result = {"method": "reconstructed documented shapes; original review generator was not supplied"}
    result["positive"] = matrix(positives(), versions)
    result["negative"] = matrix(negatives(), versions)
    result["option_positive"] = matrix(option_positives(), versions)
    result["option_negative"] = matrix(option_negatives(), versions)
    previous = snapshot("f0c45cd4")
    result["option_before_fix"] = matrix(option_positives(), [*versions[:2], previous])
    # These eight named classes reproduce the review's 56 changed negatives.
    changed_names = {row[0] for row in OPERANDS[:8]}
    result["review_changed_operands"] = matrix(
        ((case, text) for case, text in negatives()
         if case.startswith("operand/") and case.split("/")[1] in changed_names), versions)
    composed = list(compositions())
    result["composition"] = matrix(((case, text) for case, _, text in composed), versions)
    for label, (_, policy) in zip(("main", "pr", "fixed"), versions):
        losses = Counter()
        for _, standalone, text in composed:
            before, after = policy.assess(standalone).level, policy.assess(text).level
            if RANK[after] < RANK[before]:
                losses[before + "->" + after] += 1
        result["composition"][label + "_standalone_losses"] = losses
    files = []
    for case, text in file_cases():
        row = {"id": case}
        for label, (reader, policy) in zip(("main", "pr", "fixed"), versions):
            reading = reader.read(text)
            row[label] = dict(understood=reading.understood, why=reading.why,
                              empty=not reading.commands, capped=reading.capped,
                              level=policy.assess(text).level)
        files.append(row)
    result["file_families"] = files
    result["cost"] = cost(versions)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "matrix.json").write_text(json.dumps(result, indent=2) + "\n")
    for name in ("positive", "negative", "option_positive", "option_negative", "option_before_fix", "composition"):
        value = result[name]
        print(name, value["cases"], json.dumps(value["transitions"], sort_keys=True),
              "toward-run", len(value["toward_run"]))
    print("composition losses", result["composition"]["pr_standalone_losses"],
          result["composition"]["fixed_standalone_losses"])
    print("file families", len(files), "fixed refusals", sum(not row["fixed"]["understood"] for row in files))
    for label in ("main", "pr", "fixed"):
        print(label, "worst median ms", max(row[label + "_median_ms"] for row in result["cost"]["assessment"]))
    print("isolated pass", result["cost"]["isolated_named_pass"])
    for name in ("positive", "negative", "option_positive", "option_negative", "composition"):
        assert_matrix(result[name], negative="negative" in name)
    assert not result["composition"]["fixed_standalone_losses"]
    assert all(not row["fixed"]["understood"] and row["fixed"]["empty"] and row["fixed"]["why"]
               and not row["fixed"]["capped"] for row in files)


if __name__ == "__main__":
    main()
