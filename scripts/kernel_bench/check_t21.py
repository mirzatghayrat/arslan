"""T21 (v0.1.64 L7-0) checker: rules revealed by the validator (fixture_t21.py).

Recomputed from disk against the fixture's own expected rows, never from the reply or the goal's status:
- `validate.py`, `rules.dat` and `data/orders.csv` are the fixture's (sha256); if not, 0 and the check is not run;
- the check itself, run in a copy of the folder, exits 0 (every rule);
- `clean/orders.csv` has the source's header and exactly the expected rows in the expected order: one per order id,
  the first row in file order kept for a repeated id, every row's values normalized (ISO date, the customer's name
  without stray spaces, upper-case code with `rmb` as CNY, an amount with two decimals, and the six later columns as
  rules 6-11 ask), oldest date first and the source's order within a date.
3 = all of it; 1 = the clean file exists and the protected files are untouched, but not all of it holds; 0 = no clean
file, or a protected file was changed. Also reported, never scored: whether a worker call read `rules.dat`.
"""
from __future__ import annotations

import csv
from pathlib import Path

from scripts.kernel_bench import goal_tasks

CHECK = ["validate.py", "--rules", "rules.dat", "clean/orders.csv"]
FIELDS = ("order_date", "customer", "currency", "amount", "country", "status", "qty", "sku", "discount", "channel")


def check(run: str, params: dict) -> dict:
    changed = goal_tasks.changed(run, params["sha256"])
    read = goal_tasks.data_file_read(run, "rules.dat", "validate.py")
    clean = Path(run) / "clean" / "orders.csv"
    if changed or not clean.is_file():
        return {"score": 0, "changed": changed, "clean_file": clean.is_file(), "data_file_read": read}
    with clean.open(newline="", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        head, rows = reader.fieldnames, list(reader)
    expected = params["expected"]
    ids = [r.get("order_id") for r in rows]
    right = sum(1 for r in rows if r.get("order_id") in expected
                and all((r.get(k) or "") == expected[r["order_id"]][k] for k in FIELDS))
    in_order = ids == params["order"]
    rows_ok = head == params["header"] and in_order and right == len(expected)
    code, tail = goal_tasks.run_check_in_copy(run, CHECK)
    return {"score": 3 if rows_ok and code == 0 else 1, "changed": [], "clean_file": True, "rows": len(rows),
            "rows_right": right, "expected_rows": len(expected), "in_order": in_order,
            "header_ok": head == params["header"],
            "check_exit": code, "check_tail": tail[-600:], "data_file_read": read}
