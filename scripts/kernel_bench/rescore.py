"""Re-apply the current check scripts to a finished round's saved runs. No agent is run and no
model is called (rerun.py runs agents again; this only reads what a round left behind).

    python -m scripts.kernel_bench.rescore [results.jsonl] --round NAME [--out PATH]

Why (v0.1.64 M64, ②Main's recheck of #436): when the hand check of a run that decides a gate
finds a "false positive" that is a real flaw of the fixture, it goes into that task's EXTRAS (and
a correct finding scored "located" goes into the bug's keywords), and then every run of that
round is rescored, for every entrant, so all of them are judged by the same answer key.

What is read, per run: the run folder and its stdout (the record's `artifacts`), the record's
`end` for the judge, and for T16/T17 the tool-call record (Arslan's frames file next to the
folder; Claude Code's transcript by the record's `session`, under $BENCH_ROOT/home). T16's and
T17's answers are rebuilt from their fixed seeds in a scratch folder. Only RESCORABLE tasks are
rescored (the others' answers, such as T7's seed, are not kept); every other record is copied
as it was. Each rescored record keeps the check it had as `check_before`.

Writes `<results>.rescored-<round>.jsonl` (or --out) and prints the report for it.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from scripts.kernel_bench import check_t16, check_t17, report, runner

RESCORABLE = {"T13", "T14", "T15", "T16", "T17"}
SEEDED = {"T16": check_t16.fixture, "T17": check_t17.fixture}


def rescore_one(record: dict) -> dict:
    task, who = record["task"], record["entrant"]
    if task not in RESCORABLE or (record.get("check") or {}).get("unsupported"):
        return record
    run = Path(record["artifacts"]["folder"])
    ctx = {"who": who, "home": str(runner.ROOT / "home" / who), "session": record.get("session")}
    if task in SEEDED:
        with tempfile.TemporaryDirectory() as scratch:
            ctx["fixture"] = SEEDED[task](scratch)
    check = runner.CHECKS[task](str(run), runner.reply_text(who, run), ctx)
    return {
        **record,
        "check_before": record.get("check"),
        "check": check,
        "passed": runner.judge(check, record.get("end"), who),
        "rescored": True,
    }


def rescore(records: list[dict]) -> list[dict]:
    return [rescore_one(r) for r in records]


def main(argv: list[str]) -> Path:
    name = argv[argv.index("--round") + 1] if "--round" in argv else None
    out = argv[argv.index("--out") + 1] if "--out" in argv else None
    flags = {"--round", "--out"}
    args = [
        a for i, a in enumerate(argv) if not a.startswith("--") and not (i and argv[i - 1] in flags)
    ]
    path = Path(args[0]) if args else runner.ROOT / "results.jsonl"
    records = report.load(str(path))
    if name:
        records = report.in_round(records, name)
    done = rescore(records)
    dest = Path(out) if out else path.with_name(f"{path.stem}.rescored-{name or 'all'}.jsonl")
    dest.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in done))
    changed = sum(1 for r in done if r.get("rescored") and r["check"] != r["check_before"])
    rows = report.summarise(done)
    print(report.render(rows) + "\n\n" + report.render_totals(rows))
    print(
        f"\nrescored {sum(1 for r in done if r.get('rescored'))} runs, {changed} changed; wrote {dest}"
    )
    return dest


if __name__ == "__main__":
    main(sys.argv[1:])
