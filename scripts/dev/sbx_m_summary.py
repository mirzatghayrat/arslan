"""SBX-M's summary (docs/plans/0164/SBX-M-runbook.md): what the report may quote, from one run's folder.

    python3 -I scripts/dev/sbx_m_summary.py <folder>      (scripts/dev/sbx_m.sh runs it at the end)

Reads `results.xml` (the corpus), `loop/*.xml` (the listener-refusal loop) and `preflight.txt`, writes
`summary.md` next to them and prints three lines to paste back. The summary holds ids, pytest results,
measurement outcomes, probe labels, errnos, return codes, versions and counts only. A failure's text can
hold local paths or service output, so it is never copied, except an errno assertion such as
`assert 0 in (1, 13)` in the loop (tests/server/sbx/corpus/README.md: never raw command arguments,
profile text or service output).
"""
import collections
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

ERRNO_ASSERTION = re.compile(r"(?:AssertionError: )?assert -?\d+ in \((?:-?\d+, )*-?\d+,?\)")
SAFE_PROPERTIES = ("base", "outcome", "probe", "connect_errno", "returncode", "missing_tools")
FINE = {"ok", "refused"}               # any other measurement outcome is not a result yet (the README)
FIELD = re.compile(r"[^A-Za-z0-9._:+\-\[\] ,()]")      # no slash, quote, backtick or line break
LOCAL_PATH = re.compile(r"/(?:Users|private|var|tmp|Volumes)/[^\s\]]*")


def test_id(case: ET.Element) -> str:
    """pytest's node id from a JUnit testcase: `a.b.test_mod.TestC` + `test_x[p]` → `a/b/test_mod.py::TestC::test_x[p]`."""
    parts = case.get("classname", "").split(".")
    module = next((i for i, part in enumerate(parts) if part.startswith("test_")), len(parts) - 1)
    node = "::".join(["/".join(parts[:module + 1]) + ".py", *parts[module + 1:], case.get("name", "")])
    return LOCAL_PATH.sub("_", node).replace("`", "_")[:160]


def result_of(case: ET.Element) -> str:
    if case.find("failure") is not None:
        return "failed"
    if case.find("error") is not None:
        return "error"
    skipped = case.find("skipped")
    if skipped is not None:
        return "xfailed" if skipped.get("type") == "pytest.xfail" else "skipped"
    return "passed"


def properties(case: ET.Element) -> dict:
    found = collections.defaultdict(list)
    for prop in case.iterfind("properties/property"):
        found[prop.get("name", "")].append(prop.get("value", ""))
    return found


def cases(path: pathlib.Path):
    """The file's testcases, or None when it is missing or cut short (pytest stopped while writing it)."""
    try:
        return list(ET.parse(path).getroot().iter("testcase"))
    except (OSError, ET.ParseError):
        return None


def plain(value: str, limit: int = 80) -> str:
    """One short field: anything outside a small character set (a slash, a quote, a line break) becomes `_`."""
    return FIELD.sub("_", value)[:limit]


def tally(rows) -> collections.Counter:
    return collections.Counter(result_of(case) for case in rows)


def corpus_section(rows: list) -> tuple:
    results = tally(rows)
    measured, executions, look = collections.Counter(), collections.Counter(), []
    for case in rows:
        props, result = properties(case), result_of(case)
        base = (props.get("base") or [""])[-1]
        outcomes = props.get("outcome", [])
        for outcome in outcomes:
            measured[(base, outcome)] += 1
        if result != "passed" or any(outcome not in FINE for outcome in outcomes):
            look.append((test_id(case), result, {key: props[key] for key in SAFE_PROPERTIES if key in props}))
        for value in props.get("executions", []):
            for execution in json.loads(value or "[]"):
                executions[(execution.get("base", ""), execution.get("network", ""),
                            bool(execution.get("profile_override")))] += 1
    lines = [f"## The corpus: {len(rows)} cases", "",
             " · ".join(f"{name} {results[name]}" for name in ("passed", "failed", "error", "skipped", "xfailed")), "",
             "### Measurement outcomes, by base", "", "| base | outcome | rows |", "|---|---|---|"]
    lines += [f"| {plain(base)} | {plain(outcome)} | {count} |" for (base, outcome), count in sorted(measured.items())]
    lines += ["", f"### Rows that need a look ({len(look)}): not passed, or an outcome other than ok/refused", "",
              "| test id | pytest | properties |", "|---|---|---|"]
    for node, result, props in look:
        shown = "; ".join(f"{key}={','.join(plain(v, 40) for v in values)}" for key, values in props.items())
        lines.append(f"| `{node}` | {result} | {shown} |")
    lines += ["", "### Sandboxed runs, by base and network mode", "",
              "Exact hashes are per run (a profile text holds its test's scratch paths); they stay in results.xml.", "",
              "| base | network | profile overridden | runs |", "|---|---|---|---|"]
    lines += [f"| {plain(b)} | {plain(n)} | {'yes' if o else 'no'} | {count} |"
              for (b, n, o), count in sorted(executions.items())]
    return lines, len(look)


def loop_section(folder: pathlib.Path) -> tuple:
    runs = sorted(folder.glob("loop/*.xml"))
    if not runs:
        return ["## The listener-refusal loop: not run"], "loop: not run"
    counts = collections.defaultdict(collections.Counter)
    failures = collections.defaultdict(list)
    empty = []
    for run in runs:
        found = cases(run)
        if not found:
            empty.append(run.stem)
            continue
        for case in found:
            node, result = test_id(case), result_of(case)
            counts[node][result] += 1
            if result in ("failed", "error"):
                element = case.find("failure" if result == "failed" else "error")
                first = ((element.get("message") or "") if element is not None else "").strip().split("\n")[0]
                failures[node].append(f"{run.stem}: {first if ERRNO_ASSERTION.fullmatch(first) else result}")
    lines = [f"## The listener-refusal loop: {len(runs)} runs", ""]
    if empty:
        lines += [f"Runs with no results (pytest did not start, collect or finish): {', '.join(empty)}", ""]
    lines += ["| case | passed | failed | error | skipped | failed runs |", "|---|---|---|---|---|---|"]
    for node in sorted(counts):
        each = counts[node]
        lines.append(f"| `{node}` | {each['passed']} | {each['failed']} | {each['error']} | "
                     f"{each['skipped'] + each['xfailed']} | {'; '.join(failures[node]) or '-'} |")
    short = " · ".join(f"{node.rsplit('[', 1)[-1].rstrip(']')} {counts[node]['passed']}/{sum(counts[node].values())}"
                       for node in sorted(counts))
    return lines, f"loop ({len(runs)} runs, passed/ran): {short or 'no results'}"


def preflight(folder: pathlib.Path) -> list:
    path = folder / "preflight.txt"
    return [plain(line, 160) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []


def main(folder: pathlib.Path) -> str:
    rows = cases(folder / "results.xml")
    facts = preflight(folder)
    if rows is None:            # SBX_M_CORPUS=0, or pytest stopped before it wrote the file
        corpus, look, corpus_line = ["## The corpus: not run, or results.xml is cut short"], 0, "corpus: not run"
    else:
        (corpus, look), results = corpus_section(rows), tally(rows)
        corpus_line = (f"corpus: {len(rows)} cases, {results['passed']} passed, {results['failed']} failed, "
                       f"{results['error']} error, {results['skipped']} skipped, {results['xfailed']} xfailed; "
                       f"{look} rows need a look")
    loop, loop_line = loop_section(folder)
    lines = ["# SBX-M summary", "",
             "Generated by `scripts/dev/sbx_m_summary.py`: ids, results, outcomes, versions and counts only. "
             "Gaps: `tests/server/sbx/corpus/README.md` and `docs/plans/0164/SBX-M-runbook.md`.", "",
             "## This Mac", "", *[f"- {fact}" for fact in facts], "", *corpus, "", *loop, ""]
    (folder / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    head = next((fact[8:20] for fact in facts if fact.startswith("commit: ")), "?")
    mac = next((fact for fact in facts if fact.startswith("macos: ")), "macos: ?")
    return "\n".join([f"SBX-M at {head} · {mac}", corpus_line, loop_line])


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1])
    print(main(out))
    print(f"summary: {out / 'summary.md'}  (paste the three lines above; the folder stays on this Mac)")
