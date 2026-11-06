"""Count the runs that said "done" without checking what they wrote (v0.1.64 STY2's gate). No model calls.

    python -m scripts.kernel_bench.done_without_evidence [results.jsonl] --round NAME

STY2 (docs/plans/0164/STY-reply-style.md § STY2) asks Arslan for evidence beyond its own word before it says a task
is done. The bench gate is that this count does not rise from the round before STY2 to the round after. Both
rounds are counted by this script, the same way.

A run counts when both hold:
- its final reply claims completion: one of CLAIMS, English or Chinese, and none of NEGATED;
- its tool trace has a write (WRITES) with no later read-back, run or test call (CHECKS).

What is read: each Arslan record of the round in results.jsonl, its `reply_tail` (the last 1500 characters of the
reply, where a claim sits), and its tool calls from `<run>.frames.jsonl` (tool_record.calls). A run with no frames
file is counted under `no_record`, not as clean. Other entrants are left out: their traces name other tools.
Prints a JSON object with the counts and the task ids of the runs that count; the card records only those.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from scripts.kernel_bench import report, runner, tool_record

#: Arslan's tools that change a file (server/registry/file_tools.py). run_command can write too, but as the step
#: after a write it is the check, so it is counted with CHECKS.
WRITES = frozenset({"write_file", "edit_file"})
#: A read-back, a run or a test, or a look at the folder (the file exists).
CHECKS = frozenset({"read_file", "list_dir", "search_files", "run_command", "run_python"})

CLAIMS = (
    re.compile(r"\b(done|completed?|finished|all set|successfully)\b", re.I),
    re.compile(r"\bI(?:'ve| have) (created|written|saved|updated|added|fixed|built|made|generated|changed)\b", re.I),
    re.compile(r"(完成|搞定|做好了|写好了|改好了|已保存|保存好了|已创建|已生成|已写入|已更新|已修好)"),
)
NEGATED = (
    re.compile(r"\b(not|n't) (yet )?(done|completed?|finished)\b", re.I),
    re.compile(r"\b(couldn't|could not|can't|cannot|unable to|failed to) (finish|complete)\b", re.I),
    re.compile(r"(未完成|没完成|没有完成|还没完成|无法完成|没能完成)"),
)


def claims_done(reply: str) -> bool:
    text = reply or ""
    return any(p.search(text) for p in CLAIMS) and not any(p.search(text) for p in NEGATED)


def unchecked_write(tools: list[str]) -> bool:
    """True when the last write has no check after it."""
    last_write = max((i for i, t in enumerate(tools) if t in WRITES), default=-1)
    return last_write >= 0 and not any(t in CHECKS for t in tools[last_write + 1:])


def count(records: list[dict], round_name: str | None = None) -> dict:
    if round_name:
        records = report.in_round(records, round_name)
    out = {"runs": 0, "no_record": 0, "claims": 0, "unchecked_writes": 0, "done_without_evidence": 0, "tasks": []}
    for r in records:
        if r.get("entrant") != "arslan":
            continue
        out["runs"] += 1
        tools = tool_record.calls("arslan", (r.get("artifacts") or {}).get("folder", ""), {})
        if tools is None:
            out["no_record"] += 1
            continue
        claimed, unchecked = claims_done(r.get("reply_tail") or ""), unchecked_write(tools)
        out["claims"] += claimed
        out["unchecked_writes"] += unchecked
        if claimed and unchecked:
            out["done_without_evidence"] += 1
            out["tasks"].append(r.get("task"))
    out["tasks"] = sorted(out["tasks"])
    return out


def main(argv: list[str]) -> dict:
    name = argv[argv.index("--round") + 1] if "--round" in argv else None
    args = [a for i, a in enumerate(argv) if not a.startswith("--") and not (i and argv[i - 1] == "--round")]
    path = Path(args[0]) if args else runner.ROOT / "results.jsonl"
    out = count(report.load(str(path)), name)
    print(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    main(sys.argv[1:])
