"""Self-contained, text-only policy evidence; no Git metadata is read.

The default suite uses stratified historical rows and every option control.
QUOTED_ARGS_EVIDENCE_FULL=1 selects the full matrices. Historical word strata
are rule/position, expanded positives seed/position/wrapper, negatives
carrier/kind/position, compositions seed/position/tail, and the independent
sweep program/profile/position. Bucket-index rotation selects spellings.

Baseline vectors bind ordered case ids and command fingerprints by corpus digests, with verdicts
from main 3eec545b and original 9be27b5f. Generate it with:
  python -m tests.server.quoted_args_regenerate_baselines --main-source MAIN_SOURCE
      --original-source ORIGINAL_SOURCE --output tests/server/quoted_args_baselines.txt
Each source directory must contain shell_grammar.py and terminal_policy.py
exported from that revision, plus its unchanged shell_text.py. The generator
executes Python policy definitions, then passes strings only to assess/read;
it never executes the generated command text. It uses supplied sources, not
Git history. Missing or stale baseline rows fail explicitly, never skip.

The review's unpublished generator is unavailable; the sweep reconstructs its
399 profile counts and eight reported classes, not its exact input bytes.
Counts include generated duplicates. Run this module with --output to write
full matrix results; --cost additionally measures the current policy once.
"""
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import shlex
import statistics
import time

import pytest

from server.services import shell_grammar as sg, terminal_policy as tp
from tests.server.test_quoted_args_file_run import (
    FAMILIES, NAMED, OPERANDS, OPTION_NEGATIVES, OPTION_OPERATIONS, POSITIONS,
    RANK, REFUSED_TAILS, operand_text, spelled,
)
from tests.server.test_quoted_command_word import CASES, RULES, SEPARATORS, SHELL_CASES
from tests.server.shell_differential_support import FILE_SEEDS


from tests.server.quoted_args_baseline_data import levels
from tests.server.quoted_args_option_profiles import (
    sweep, program_controls, unknowns, render, vercel_directories, implicit_controls, implicit_negative_controls, cluster_controls,
    DEPLOY_PROGRAMS,
)


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
            for carrier, wrap in carriers.items():
                for position, before in SEPARATORS.items():
                    yield f"data/{i}/{kind}/{carrier}/{position}", before + wrap(shlex.quote(data))
                for j, separator in enumerate(separators):
                    yield f"data/{i}/{kind}/{carrier}/inside-{j}", wrap(shlex.quote("prefix" + separator + data))
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
        elif parts[0] == "sweep":
            key = tuple(parts[:3] + parts[4:])
        elif parts[0] == "data":
            key = tuple(parts[:1] + parts[2:])
        else:
            key = tuple(parts)
        buckets[key].append(row)
    return [bucket[i % len(bucket)] for i, bucket in enumerate(buckets.values())]


def step3_move(row):
    return (row["main"], row["fixed"], row.get("rule")) == ("run", "ask", tp.UNREADABLE)


def test_step3_move_is_only_run_to_ask_unreadable():
    assert step3_move({"main": "run", "fixed": "ask", "rule": tp.UNREADABLE})
    assert not step3_move({"main": "run", "fixed": "ask", "rule": "stand-in-rule"})
    assert not step3_move({"main": "run", "fixed": "forbid", "rule": tp.UNREADABLE})
    assert not step3_move({"main": "ask", "fixed": "run", "rule": ""})
    assert not step3_move({"main": "forbid", "fixed": "ask", "rule": tp.UNREADABLE})


def assert_matrix(result, *, negative=False, cautious_forbids=False):
    assert not result["toward_run"], result["toward_run"]
    if negative:
        # Exactly seven accepted cautious forbids: the unsplittable cluster
        # keeps 9be27b5f's verdict. Whitespace cannot imply an operand; the
        # --exclude=a b and -d"foo bar" controls retain option/value protection.
        accepted = {f"operand/wipe-root-option-looking-file/{position}"
                    for position in SEPARATORS}
        # S2a-3 step 3: a command the reader does not understand asks as `unreadable` (offline in the sandbox, no
        # card) where main ran it. That move is set aside; every other change from main is still checked below.
        changes = [row for row in result["changed_from_main"] if not step3_move(row)]
        if cautious_forbids:
            assert {row["id"] for row in changes} == accepted, changes
            assert all((row["main"], row["pr"], row["fixed"]) ==
                       ("run", "forbid", "forbid") for row in changes), changes
        else:
            assert not changes, changes
    elif result.get("kind") != "cluster":
        regressions = {transition: count for transition, count in result["transitions"]["pr_to_fixed"].items()
                       if RANK[transition.split("->")[1]] < RANK[transition.split("->")[0]]}
        assert not regressions, result["losses"]


def control_rows():
    return ((case, render(words, "single", "plain")) for case, words in program_controls())


def unknown_rows():
    return ((case, render(words, "single", "plain")) for case, words in unknowns())


GENERATORS = {
    "positive": positives, "negative": negatives,
    "option-positive": option_positives, "option-negative": option_negatives,
    "sweep": sweep, "controls": control_rows, "unknown": unknown_rows,
    "composition": lambda: ((case, text) for case, _, text in compositions()),
    "standalone": lambda: ((case, text) for case, text, _ in compositions()),
    "files": file_cases,
    "vercel": vercel_directories,
    "implicit": lambda: ((case, render(words, "single", "plain")) for case, words, _, _ in implicit_controls()),
    "cluster": lambda: ((case, text) for case, _, _, text in cluster_controls()),
}


def assert_accounting(kind):
    if kind == "implicit":
        for case, words, flag, rule in implicit_controls():
            assert tp._fully_accounted(words[0], words[1:]), case
            assert flag in tp._dispatch_args(words[0], words[1:])[1], case
            assert rule in tp._named_rules(words), case
    if kind == "cluster":
        for case, words, accounted, text in cluster_controls():
            assert tp._fully_accounted(words[0], words[1:]) == accounted, case
            original = levels(kind, case, text)[1]
            actual = tp.assess(text).level
            if not accounted:
                assert actual == original, case
            elif case.endswith("/single/plain"):
                assert (original, actual) == ("ask", "run"), case
    if kind not in {"controls", "unknown"}:
        return
    source = program_controls if kind == "controls" else unknowns
    for case, words in source():
        expected = kind == "controls"
        assert tp._fully_accounted(words[0], words[1:]) == expected, case
        if not expected:
            # #821: on a deploy CLI, an unknown option before the verb leaves the verb unplaceable, which asks as `publish`
            unplaceable = {"publish"} if words[0] in DEPLOY_PROGRAMS and case.endswith("/before") else set()
            assert tp._named_rules(words) == tp._legacy_named_rules(words) | unplaceable, case


@pytest.mark.parametrize("kind", [kind for kind in GENERATORS if kind not in {"standalone", "vercel", "cluster"}])
def test_stored_baseline_evidence(kind, record_property):
    assert_accounting(kind)
    rows = stratified(GENERATORS[kind]())
    for case, text in rows:
        reading = sg.read(text)
        if kind == "files":
            assert not reading.understood and reading.why and not reading.commands and not reading.capped, case
            # Main and the original ran a script; since S2a-3 step 3 the reader's refusal asks as `unreadable`.
            assert levels(kind, case, text) == ("run", "run"), case
            head = tp.assess(text)
            assert (head.level, head.rule) == ("ask", tp.UNREADABLE), case
    if kind == "composition":
        for case, standalone, text in stratified(compositions()):
            assert not sg.read(text).understood and not sg.read(text).commands, case
            assert RANK[tp.assess(text).level] >= RANK[tp.assess(standalone).level], case
    if kind == "vercel":
        for case, text in rows:
            actual = tp.assess(text).level[0]
            assert actual == "a", f"{kind}/{case}: expected a, actual {actual}"
    if kind != "files":
        assert_matrix(matrix(kind, rows), negative="negative" in kind,
                      cautious_forbids=kind == "negative")
    record_property("generated_rows", len(rows))


def test_vercel_production_directory_retains_publish(record_property):
    test_stored_baseline_evidence("vercel", record_property)


def test_cluster_value_does_not_absorb_following_unknown(record_property):
    test_stored_baseline_evidence("cluster", record_property)


def matrix(kind, rows):
    transitions = defaultdict(Counter)
    classes = defaultdict(Counter)
    changes = []
    toward_run = []
    fallbacks = Counter()
    fallback_cases = []
    count = 0
    loosened = []
    losses = []
    for case, text in rows:
        count += 1
        sg.read(text)
        head = tp.assess(text)
        verdicts = [*levels(kind, case, text), head.level]
        fallback_programs = {words[0].lower() for words in tp._command_words(text)
                             if not tp._fully_accounted(words[0].lower(), words[1:])}
        if fallback_programs:
            fallback_cases.append(case)
            fallbacks.update(fallback_programs)
        for a, b, label in ((0, 1, "main_to_pr"), (0, 2, "main_to_fixed"), (1, 2, "pr_to_fixed")):
            transition = verdicts[a] + "->" + verdicts[b]
            transitions[label][transition] += 1
            classes[case.split("/")[0] + "/" + label][transition] += 1
        if RANK[verdicts[2]] < RANK[verdicts[1]]:
            loosened.append(case)
            losses.append(f"{kind}/{case}: expected >= {verdicts[1][0]}, actual {verdicts[2][0]}")
        if verdicts[0] != verdicts[2]:
            changes.append({"id": case, "main": verdicts[0], "pr": verdicts[1], "fixed": verdicts[2],
                            "rule": head.rule, "matrix": kind, "expected": verdicts[0][0], "actual": verdicts[2][0]})
        if RANK[verdicts[2]] < RANK[verdicts[0]]:
            toward_run.append(f"{kind}/{case}: expected >= {verdicts[0][0]}, actual {verdicts[2][0]}")
    return dict(kind=kind, cases=count, loosened=loosened, losses=losses, transitions=dict(transitions), by_class=dict(classes),
                changed_from_main=changes, toward_run=toward_run,
                fallback_cases=fallback_cases, fallback_programs=dict(fallbacks))


def clear(policy):
    for value in vars(policy).values():
        if hasattr(value, "cache_clear"):
            value.cache_clear()


def cost(versions, labels=("main", "pr", "fixed")):
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
            for label, (_, policy) in zip(labels, versions):
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
        passes = [("fixed", lambda: tp._named_rules(words))]
        if len(versions) > 1:
            old = versions[1][1]
            passes.insert(0, ("pr", lambda: [pattern.match(" ".join(words))
                                           for _, pattern, _, masked in old._FORBID_C if not masked]))
        for label, run in passes:
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
    parser.add_argument("--cost", action="store_true")
    args = parser.parse_args()
    result = {}
    for kind, generate in GENERATORS.items():
        assert_accounting(kind)
        if kind == "standalone":
            continue
        result[kind] = matrix(kind, generate())
        print(kind, result[kind]["cases"], dict(result[kind]["transitions"]["pr_to_fixed"]),
              "fallbacks", len(result[kind]["fallback_cases"]), flush=True)
    losses = Counter()
    for case, standalone, text in compositions():
        before, after = tp.assess(standalone).level, tp.assess(text).level
        if RANK[after] < RANK[before]:
            losses[before + "->" + after] += 1
    result["composition"]["fixed_standalone_losses"] = dict(losses)
    if args.cost:
        result["cost"] = cost([(sg, tp)], labels=("fixed",))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "matrix.json").write_text(json.dumps(result, indent=2) + "\n")
    for kind in GENERATORS:
        if kind not in {"files", "standalone"}:
            assert_matrix(result[kind], negative="negative" in kind,
                          cautious_forbids=kind == "negative")
    assert not losses, losses


@pytest.mark.parametrize("case,words", list(implicit_negative_controls()), ids=lambda value: value if isinstance(value, str) else None)
def test_operation_looking_data_does_not_select_publish(case, words):
    command = render(words, "single", "plain")
    assert sg.read(command).understood, case
    assert tp._fully_accounted(words[0], words[1:]), case
    assert tp._dispatch_args(words[0], words[1:])[1] == frozenset(), case
    assert tp.assess(command).level == "run", case  # Main and original also run.


if __name__ == "__main__":
    main()
