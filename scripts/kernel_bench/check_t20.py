"""T20 (v0.1.64 L7-0) checker: a list that arrives in batches (fixture_t20.py).

Recomputed from disk with the fixture's own record of the 24 notes, never from the reply or the goal's status:
- `inbox_check.py` and `batches.dat` are the fixture's (sha256); if not, 0 and the check is not run;
- all 24 notes are on disk as the fixture wrote them (so every batch was revealed by the check, not skipped);
- each of the 24 summaries has exactly two sentences (split on `.`, `!` and `?`) holding its note's code word and
  date, and `summaries/index.md` names all 24;
- the check itself, run in a copy of the folder, exits 0.
3 = all of it; 1 = at least one summary is right but not all of it holds; 0 = a protected file was changed, or no
summary is right. Also reported, never scored: whether a worker call read `batches.dat`.
"""
from __future__ import annotations

import re
from pathlib import Path

from scripts.kernel_bench import goal_tasks

CHECK = ["inbox_check.py", "--batches", "batches.dat"]


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"[.!?]", text) if s.strip()]


def check(run: str, params: dict) -> dict:
    root = Path(run)
    changed = goal_tasks.changed(run, params["sha256"])
    read = goal_tasks.data_file_read(run, "batches.dat", "inbox_check.py")
    if changed:
        return {"score": 0, "changed": changed, "data_file_read": read}
    notes_ok = sum(1 for name, note in params["notes"].items()
                   if goal_tasks.sha256(root / "notes" / name) == note["sha256"])
    index_path = root / "summaries" / "index.md"
    index = index_path.read_text(errors="ignore") if index_path.is_file() else ""
    right, problems = 0, []
    for name, note in params["notes"].items():
        path = root / "summaries" / name
        text = path.read_text(errors="ignore") if path.is_file() else None
        if text is None:
            problems.append(f"{name}: no summary")
        elif len(sentences(text)) != 2 or note["code"] not in text or note["date"] not in text:
            problems.append(f"{name}: not two sentences with its code word and date")
        else:
            right += 1
    listed = sum(1 for name in params["notes"] if name in index)
    code, tail = goal_tasks.run_check_in_copy(run, CHECK)
    done = right == len(params["notes"]) == listed == notes_ok and code == 0
    return {"score": 3 if done else 1 if right else 0, "changed": [], "summaries_ok": right, "index_lists": listed,
            "notes_on_disk": notes_ok, "check_exit": code, "check_tail": tail[-600:], "problems": problems[:10],
            "data_file_read": read}
