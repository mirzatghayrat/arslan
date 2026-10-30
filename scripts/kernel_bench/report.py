"""Summarise a bench run: Pass^k per task, entrant and model, plus cost, model time and calls.

    python -m scripts.kernel_bench.report [results.jsonl] [--offpeak]

Pass^k = every one of the k repeats passed (score 3). That is the reliability bar; a
single success only shows a task is possible. The same entrant on two models is two rows.
Cost is shown at peak price, or halved with --offpeak (DeepSeek off-peak hours; it does not
apply to Claude models, so compare those rows without it). --round NAME keeps only that round's
runs (labels ending in `-NAME`, runner.ROUND).

Under the table, per entrant and model, two totals of tasks passed every time (v0.1.64 M64):
the old figure over every task, an unsupported task counting as not passed, and the same-task
figure over only the tasks every entrant on that model supports (R64's gate uses the second).
Code-review tasks (T13–T15) add bugs caught / planted and false positives, summed over repeats.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path


def load(path: str) -> list[dict]:
    return [json.loads(line) for line in open(path) if line.strip()]


def summarise(records: list[dict], offpeak: bool = False) -> list[dict]:
    groups: dict = defaultdict(list)
    for r in records:
        # Rows judged by an older pass rule (score only, before M1a) never mix with newer ones.
        groups[(r["task"], r["entrant"], r.get("model", "?"), r.get("judge", 1))].append(r)
    rows = []
    for (task, who, model, judged), rs in sorted(groups.items()):
        k = len(rs)
        passes = sum(1 for r in rs if r.get("passed"))
        usd = sum(r["usage"]["usd_peak"] for r in rs) / k / (2 if offpeak else 1)
        checks = [r.get("check") or {} for r in rs]
        review = [c for c in checks if "planted" in c]
        rows.append({"task": task, "entrant": who, "old_rule": judged < 2, "model": model, "k": k, "passes": passes, "pass_all": passes == k,
                     "unsupported": any(c.get("unsupported") for c in checks),
                     "review": {"caught": sum(c["caught"] for c in review), "planted": sum(c["planted"] for c in review),
                                "false_positives": sum(c["false_positives"] for c in review)} if review else None,
                     "mean_usd": round(usd, 4),
                     "mean_span_s": round(sum(r["usage"]["span_s"] for r in rs) / k, 1),
                     "mean_calls": round(sum(r["usage"]["model_calls"] for r in rs) / k, 1),
                     "ends": sorted({str(r.get("rc")) for r in rs})})
    return rows


def totals(rows: list[dict]) -> list[dict]:
    """Per entrant and model: tasks passed every time (Pass^k) over every task it has rows for, an
    unsupported task counting as not passed (the old figure), and over the same tasks only: those
    every entrant on that model ran (has rows for, none unsupported)."""
    by_model: dict = defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)
    out = []
    for model, rs in sorted(by_model.items()):
        groups = sorted({(r["entrant"], r["old_rule"]) for r in rs})
        tasks = {r["task"] for r in rs}
        same = set(tasks)
        for g in groups:
            same &= {r["task"] for r in rs if (r["entrant"], r["old_rule"]) == g and not r["unsupported"]}
        for who, old in groups:
            mine = [r for r in rs if (r["entrant"], r["old_rule"]) == (who, old)]
            out.append({"entrant": who, "old_rule": old, "model": model, "k": sorted({r["k"] for r in mine}),
                        "pass_all": sum(1 for r in mine if r["pass_all"]), "tasks": len(tasks),
                        "same_pass_all": sum(1 for r in mine if r["pass_all"] and r["task"] in same),
                        "same_tasks": len(same), "same": sorted(same)})
    return out


def paired(records: list[dict]) -> dict:
    """task -> repeat -> {entrant: passed}: who passed on the same task and repeat."""
    out: dict = defaultdict(lambda: defaultdict(dict))
    for r in records:
        out[r["task"]][r["repeat"]][r["entrant"]] = r.get("passed")
    return {t: dict(v) for t, v in out.items()}


def render(rows: list[dict]) -> str:
    lines = ["| task | entrant | model | Pass^k | passes | mean $ | model time | calls | caught / planted | false pos. |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        who = r["entrant"] + (" (old rule)" if r.get("old_rule") else "")
        review = r.get("review")
        found = f"{review['caught']}/{review['planted']} | {review['false_positives']}" if review else "— | —"
        lines.append(f"| {r['task']} | {who} | {r['model']} | {'yes' if r['pass_all'] else 'no'} | "
                     f"{r['passes']}/{r['k']} | "
                     f"{r['mean_usd']:.3f} | {r['mean_span_s']}s | {r['mean_calls']} | {found} |")
    return "\n".join(lines)


def render_totals(rows: list[dict]) -> str:
    lines = ["| entrant | model | k | Pass^k, every task (unsupported = 0) | same-task Pass^k | same tasks |",
             "| --- | --- | --- | --- | --- | --- |"]
    for t in totals(rows):
        who = t["entrant"] + (" (old rule)" if t["old_rule"] else "")
        lines.append(f"| {who} | {t['model']} | {','.join(map(str, t['k']))} | {t['pass_all']}/{t['tasks']} | "
                     f"{t['same_pass_all']}/{t['same_tasks']} | {' '.join(t['same'])} |")
    return "\n".join(lines)


def sandbox_cards(records: list[dict]) -> dict:
    """SBX-7: per entrant and model, the runs that counted cards to run outside the sandbox, and the cards: a
    re-run after the sandbox stopped a command, or asked up front. SBX-8 compares the re-runs per run."""
    out: dict = {}
    for r in records:
        cards = r.get("sandbox_cards") or {}
        if cards.get("retry") is None and cards.get("outside") is None:
            continue
        seen = out.setdefault((r["entrant"], r.get("model", "?")), {"runs": 0, "retry": 0, "outside": 0})
        seen["runs"] += 1
        seen["retry"] += cards.get("retry") or 0
        seen["outside"] += cards.get("outside") or 0
    return out


def render_sandbox_cards(records: list[dict]) -> str:
    lines = ["| entrant | model | runs | re-run cards | re-runs per run | asked up front |",
             "| --- | --- | --- | --- | --- | --- |"]
    for (who, model), c in sorted(sandbox_cards(records).items()):
        lines.append(f"| {who} | {model} | {c['runs']} | {c['retry']} | {c['retry'] / c['runs']:.2f} | {c['outside']} |")
    return "\n".join(lines)


def in_round(records: list[dict], name: str) -> list[dict]:
    return [r for r in records if str(r.get("run", "")).endswith(f"-{name}")]


if __name__ == "__main__":
    argv = sys.argv[1:]
    name = argv[argv.index("--round") + 1] if "--round" in argv else None
    args = [a for i, a in enumerate(argv) if not a.startswith("--") and not (i and argv[i - 1] == "--round")]
    path = args[0] if args else str(Path(os.environ.get("BENCH_ROOT", "/tmp/arslan-kernel-bench")) / "results.jsonl")
    recs = load(path)
    if name:
        recs = in_round(recs, name)
    rows = summarise(recs, offpeak="--offpeak" in sys.argv)
    print(render(rows))
    print()
    print(render_totals(rows))
    print()
    print(render_sandbox_cards(recs))
