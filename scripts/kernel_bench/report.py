"""Summarise a bench run: Pass^k per task and entrant, plus cost, model time and calls.

    python -m scripts.kernel_bench.report [results.jsonl] [--offpeak]

Pass^k = every one of the k repeats passed (score 3). That is the reliability bar; a
single success only shows a task is possible. Cost is shown at DeepSeek peak price, or
halved with --offpeak (Chinese public holidays and off-peak hours).
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
        groups[(r["task"], r["entrant"])].append(r)
    rows = []
    for (task, who), rs in sorted(groups.items()):
        k = len(rs)
        passes = sum(1 for r in rs if r.get("passed"))
        usd = sum(r["usage"]["usd_peak"] for r in rs) / k / (2 if offpeak else 1)
        rows.append({"task": task, "entrant": who, "k": k, "passes": passes, "pass_all": passes == k,
                     "mean_usd": round(usd, 4),
                     "mean_span_s": round(sum(r["usage"]["span_s"] for r in rs) / k, 1),
                     "mean_calls": round(sum(r["usage"]["model_calls"] for r in rs) / k, 1),
                     "ends": sorted({str(r.get("rc")) for r in rs})})
    return rows


def paired(records: list[dict]) -> dict:
    """task -> repeat -> {entrant: passed}: who passed on the same task and repeat."""
    out: dict = defaultdict(lambda: defaultdict(dict))
    for r in records:
        out[r["task"]][r["repeat"]][r["entrant"]] = r.get("passed")
    return {t: dict(v) for t, v in out.items()}


def render(rows: list[dict]) -> str:
    lines = ["| task | entrant | Pass^k | passes | mean $ | model time | calls |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        lines.append(f"| {r['task']} | {r['entrant']} | {'yes' if r['pass_all'] else 'no'} | {r['passes']}/{r['k']} | "
                     f"{r['mean_usd']:.3f} | {r['mean_span_s']}s | {r['mean_calls']} |")
    return "\n".join(lines)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else str(Path(os.environ.get("BENCH_ROOT", "/tmp/arslan-kernel-bench")) / "results.jsonl")
    recs = load(path)
    print(render(summarise(recs, offpeak="--offpeak" in sys.argv)))
