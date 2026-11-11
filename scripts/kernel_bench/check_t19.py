"""T19 (v0.1.64 L7-0) checker: staged test failures (fixture_t19.py).

Recomputed from disk, never from the reply or the goal's own status:
- `tests/run_checks.py` and `tests/stages.dat` are the fixture's (sha256); if not, 0 and the check is not run;
- the check itself, run in a copy of the folder, exits 0 (in a copy, so a check that would reveal one more step
  writes there, not into the folder being judged);
- a hidden suite of every module, with cases the revealed tests don't have, passes. It is never written into the
  run folder, so a fix that only fits the revealed tests fails it.
3 = all three; 1 = the files are the fixture's and at least one module passes its hidden cases, but not all of it
holds; 0 = a protected file was changed, or no module passes.
Also reported, never scored: whether a worker call read the encoded data file (the L7 card's disclosed residual).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.kernel_bench import goal_tasks

CHECK = ["tests/run_checks.py"]

HIDDEN = {
    "money": '''from decimal import Decimal
from ledger.money import to_cents
assert to_cents("0.135") == 14
assert to_cents("1.005") == 101
assert to_cents("-2.675") == -268
assert to_cents(Decimal("3.333")) == 333
assert to_cents("7") == 700
''',
    "dates": '''import datetime
from ledger.dates import parse_date
assert parse_date("01/02/2024") == datetime.date(2024, 2, 1)
assert parse_date(" 9/11/2026 ") == datetime.date(2026, 11, 9)
assert parse_date("29/02/2028") == datetime.date(2028, 2, 29)
''',
    "ordering": '''import datetime
from ledger.ordering import sort_entries
d = [datetime.date(2026, 2, n) for n in (1, 2, 3)]
e = [{"id": "p", "date": d[2], "cents": 1}, {"id": "q", "date": d[0], "cents": 10},
     {"id": "r", "date": d[0], "cents": 300}, {"id": "s", "date": d[1], "cents": -5},
     {"id": "t", "date": d[0], "cents": 10}]
assert [x["id"] for x in sort_entries(e)] == ["r", "q", "t", "s", "p"]
assert sort_entries([]) == []
''',
    "periods": '''import datetime
from ledger.periods import fiscal_quarter
assert fiscal_quarter(datetime.date(2026, 7, 1)) == ("FY2026", 2)
assert fiscal_quarter(datetime.date(2026, 1, 1)) == ("FY2025", 4)
assert fiscal_quarter(datetime.date(2026, 10, 31)) == ("FY2026", 3)
assert fiscal_quarter(datetime.date(2027, 3, 1)) == ("FY2026", 4)
''',
    "statement": '''from ledger.statement import format_amount
assert format_amount(-123456789) == "(1,234,567.89)"
assert format_amount(5) == "0.05"
assert format_amount(-1) == "(0.01)"
assert format_amount(100000000) == "1,000,000.00"
''',
    "shares": '''from ledger.shares import split_evenly
assert split_evenly(5, 3) == [2, 2, 1]
assert split_evenly(0, 2) == [0, 0]
assert split_evenly(1001, 4) == [251, 250, 250, 250]
assert split_evenly(7, 1) == [7]
''',
    "accounts": '''from ledger.accounts import normalise_account
assert normalise_account("xy-1234") == "XY1234"
assert normalise_account("b 5") == "B0005"
assert normalise_account("Qr--0042") == "QR0042"
''',
}

SUITE = '''import json, sys, traceback
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
cases = json.loads(sys.argv[2])
out = {}
for name, code in cases.items():
    try:
        exec(compile(code, "hidden_" + name, "exec"), {})
        out[name] = True
    except BaseException:
        out[name] = False
print(json.dumps(out))
'''


def hidden(run: str) -> dict[str, bool]:
    """Each module's hidden cases, run against the run folder's `ledger/` in a separate process."""
    try:
        done = subprocess.run([goal_tasks.python3(), "-B", "-I", "-c", SUITE, str(Path(run).resolve()),
                               json.dumps(HIDDEN)], capture_output=True, text=True, timeout=60,
                              env={"PATH": goal_tasks.INSTANCE_PATH})
        result = json.loads(done.stdout.strip().splitlines()[-1])
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        return {name: False for name in HIDDEN}
    return {name: result.get(name) is True for name in HIDDEN}


def check(run: str, params: dict) -> dict:
    changed = goal_tasks.changed(run, params["sha256"])
    read = goal_tasks.data_file_read(run, "stages.dat", "run_checks.py")
    revealed = sorted(p.name for p in (Path(run) / "tests" / "revealed").glob("test_step_*.py"))
    if changed:
        return {"score": 0, "changed": changed, "data_file_read": read, "steps_revealed": len(revealed)}
    code, tail = goal_tasks.run_check_in_copy(run, CHECK)
    suite = hidden(run)
    done = code == 0 and all(suite.values())
    return {"score": 3 if done else 1 if any(suite.values()) else 0, "changed": [], "check_exit": code, "check_tail": tail[-600:],
            "hidden": suite, "steps_revealed": len(revealed), "data_file_read": read}
