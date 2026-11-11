"""Kernel bench L7-0 (v0.1.64, goal mode): the goal task T18, the multi-round tasks T19–T21, BENCH_GOAL in the
driver, per-task repeats and the completion bar in the report. No model calls: each task is solved here by a
hand-written stand-in, independently of the fixture's own code, and the staged checks are run for real."""

import asyncio
import csv
import io
import json
import re
import shutil
import subprocess
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from scripts.kernel_bench import (
    arslan_driver,
    check_t18,
    check_t19,
    check_t20,
    check_t21,
    fixture_t19,
    fixture_t20,
    fixture_t21,
    goal_tasks,
    report,
    runner,
)

PY = goal_tasks.python3()


def _run(folder: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, "-B", *argv], cwd=folder, capture_output=True, text=True, timeout=60
    )


def _files(folder: Path) -> set[str]:
    return {
        str(p.relative_to(folder))
        for p in folder.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }


# ── T18: 20 invoices to sort and reconcile ────────────────────────────────────

MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def _read_invoice(text: str) -> dict:
    """The stand-in's own reading of one invoice (not check_t18's)."""
    number = re.search(r"^INVOICE (\S+)", text, re.M).group(1)
    raw = re.search(r"^Date: (.+)$", text, re.M).group(1).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        day = raw
    else:
        d, mon, y = raw.split()
        day = f"{int(y):04d}-{MONTHS[mon]:02d}-{int(d):02d}"
    vendor = re.search(r"^Vendor: (.+)$", text, re.M).group(1).strip()
    total = Decimal(0)
    for qty, price in re.findall(r"^\s+(\d+) x (\d+\.\d{2})\s", text, re.M):
        total += int(qty) * Decimal(price)
    shipping = re.search(r"^Shipping: (\d+\.\d{2})$", text, re.M)
    if shipping:
        total += Decimal(shipping.group(1))
    stated = Decimal(re.search(r"^Stated total: (\d+\.\d{2})$", text, re.M).group(1))
    return {"invoice": number, "date": day, "vendor": vendor, "computed": total, "stated": stated}


def _t18_ledger(run: Path) -> list[list[str]]:
    rows = sorted(
        (_read_invoice(p.read_text()) for p in (run / "invoices").iterdir()),
        key=lambda r: (r["date"], r["invoice"]),
    )
    out = [["invoice", "date", "vendor", "computed_total", "stated_total", "status"]]
    for r in rows:
        status = "ok" if r["computed"] == r["stated"] else "mismatch"
        out.append([r["invoice"], r["date"], r["vendor"], f"{r['computed']:.2f}", f"{r['stated']:.2f}", status])
    out.append(["TOTAL", "", "", f"{sum(r['computed'] for r in rows):.2f}", "", ""])
    return out


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    path.write_text(buf.getvalue())


def test_t18_writes_twenty_invoices_with_four_wrong_totals_and_two_date_styles(tmp_path):
    params = check_t18.fixture(str(tmp_path))
    names = sorted(p.name for p in (tmp_path / "invoices").iterdir())
    assert len(names) == 20 and _files(tmp_path) == {f"invoices/{n}" for n in names}
    read = [_read_invoice((tmp_path / "invoices" / n).read_text()) for n in names]
    assert sum(r["computed"] != r["stated"] for r in read) == 4
    assert {r["invoice"] for r in read} == {t["invoice"] for t in params["truth"]}
    texts = [(tmp_path / "invoices" / n).read_text() for n in names]
    assert any(re.search(r"^Date: \d{4}-", t, re.M) for t in texts)
    assert any(re.search(r"^Date: \d{1,2} [A-Z][a-z]{2} \d{4}$", t, re.M) for t in texts)
    # the file names don't give the order away
    by_name = [r["invoice"] for r in read]
    by_date = [r["invoice"] for r in sorted(read, key=lambda r: (r["date"], r["invoice"]))]
    assert by_name != by_date


def test_t18_the_checker_recomputes_what_the_stand_in_computed(tmp_path):
    params = check_t18.fixture(str(tmp_path))
    truth = {t["invoice"]: t for t in params["truth"]}
    for row in _t18_ledger(tmp_path)[1:-1]:
        t = truth[row[0]]
        assert (row[1], row[3], row[4]) == (t["date"], t["computed_total"], t["stated_total"])


def test_t18_a_right_ledger_scores_three_and_the_reply_plays_no_part(tmp_path):
    params = check_t18.fixture(str(tmp_path))
    _write_csv(tmp_path / "ledger.csv", _t18_ledger(tmp_path))
    verdict = check_t18.check(str(tmp_path), params)
    assert verdict["score"] == 3, verdict
    assert "reply" not in check_t18.check.__code__.co_varnames


@pytest.mark.parametrize("damage", ["order", "status", "total_row", "cents", "missing_row"])
def test_t18_one_wrong_thing_in_the_ledger_is_not_complete(tmp_path, damage):
    params = check_t18.fixture(str(tmp_path))
    rows = _t18_ledger(tmp_path)
    if damage == "order":
        rows[1], rows[2] = rows[2], rows[1]
    elif damage == "status":
        i = next(i for i, r in enumerate(rows) if r[5] == "mismatch")
        rows[i][5] = "ok"
    elif damage == "total_row":
        rows = rows[:-1]
    elif damage == "cents":
        rows[3][3] = f"{Decimal(rows[3][3]) + Decimal('0.01'):.2f}"
    else:
        del rows[5]
    _write_csv(tmp_path / "ledger.csv", rows)
    verdict = check_t18.check(str(tmp_path), params)
    assert verdict["score"] == 1, (damage, verdict)


def test_t18_no_ledger_or_a_changed_invoice_scores_zero(tmp_path):
    params = check_t18.fixture(str(tmp_path))
    assert check_t18.check(str(tmp_path), params)["score"] == 0
    first = sorted((tmp_path / "invoices").iterdir())[0]
    text = first.read_text()
    first.write_text(re.sub(r"Stated total: .*", "Stated total: 0.00", text))
    _write_csv(tmp_path / "ledger.csv", _t18_ledger(tmp_path))   # right for the edited files
    verdict = check_t18.check(str(tmp_path), params)
    assert verdict["score"] == 0 and verdict["invoices_changed"] == [f"invoices/{first.name}"]


# ── T19: staged test failures ─────────────────────────────────────────────────

T19_FIXED = {
    "money.py": (
        "from decimal import Decimal, ROUND_HALF_UP\n\n\n"
        "def to_cents(amount):\n"
        "    return int((Decimal(str(amount)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))\n"
    ),
    "dates.py": (
        "import datetime\n\n\n"
        "def parse_date(text):\n"
        "    return datetime.datetime.strptime(text.strip(), '%d/%m/%Y').date()\n"
    ),
    "ordering.py": (
        "def sort_entries(entries):\n"
        "    return sorted(entries, key=lambda e: (e['date'], -e['cents']))\n"
    ),
    "periods.py": (
        "def fiscal_quarter(day):\n"
        "    start = day.year if day.month >= 4 else day.year - 1\n"
        "    return ('FY%d' % start, (day.month - 4) % 12 // 3 + 1)\n"
    ),
    "statement.py": (
        "def format_amount(cents):\n"
        "    text = '{:,}.{:02d}'.format(abs(cents) // 100, abs(cents) % 100)\n"
        "    return '(%s)' % text if cents < 0 else text\n"
    ),
}


def test_t19_starts_with_five_buggy_modules_and_only_the_first_steps_tests(tmp_path):
    params = fixture_t19.fixture(str(tmp_path))
    assert sorted(p.name for p in (tmp_path / "ledger").glob("*.py")) == sorted(
        ["__init__.py", *T19_FIXED]
    )
    assert sorted(p.name for p in (tmp_path / "tests" / "revealed").iterdir()) == ["test_step_1.py"]
    assert set(params["sha256"]) == {"tests/run_checks.py", "tests/stages.dat"}
    # what later steps expect is not in any readable file
    readable = "".join(p.read_text() for p in tmp_path.rglob("*.py"))
    assert "format_amount(-5000)" not in readable and "FY2025" not in readable
    first = _run(tmp_path, "tests/run_checks.py")
    assert first.returncode == 1 and "to_cents" in first.stdout


def test_t19_each_step_appears_only_after_the_one_before_passes(tmp_path):
    fixture_t19.fixture(str(tmp_path))
    revealed = tmp_path / "tests" / "revealed"
    runs = 0
    for step, module in enumerate(T19_FIXED, 1):
        out = _run(tmp_path, "tests/run_checks.py")
        runs += 1
        assert out.returncode == 1 and len(list(revealed.glob("test_step_*.py"))) == step, out.stdout
        (tmp_path / "ledger" / module).write_text(T19_FIXED[module])
        out = _run(tmp_path, "tests/run_checks.py")
        runs += 1
        if step < len(T19_FIXED):
            assert out.returncode == 1 and "new tests were added" in out.stdout.lower(), out.stdout
            assert (revealed / f"test_step_{step + 1}.py").is_file()
        else:
            assert out.returncode == 0, out.stdout
    assert _files(tmp_path) >= {f"tests/revealed/test_step_{k}.py" for k in range(1, 6)}
    assert not list(tmp_path.rglob("__pycache__"))       # the runner writes no bytecode beside the tests


def test_t19_fixing_everything_up_front_still_takes_four_check_runs_after_the_first(tmp_path):
    fixture_t19.fixture(str(tmp_path))
    for name, source in T19_FIXED.items():
        (tmp_path / "ledger" / name).write_text(source)
    codes = [_run(tmp_path, "tests/run_checks.py").returncode for _ in range(5)]
    assert codes == [1, 1, 1, 1, 0]


def _t19_done(tmp_path: Path) -> dict:
    params = fixture_t19.fixture(str(tmp_path))
    for name, source in T19_FIXED.items():
        (tmp_path / "ledger" / name).write_text(source)
    while _run(tmp_path, "tests/run_checks.py").returncode != 0:
        pass
    return params


def test_t19_all_fixed_and_all_steps_revealed_scores_three(tmp_path):
    params = _t19_done(tmp_path)
    verdict = check_t19.check(str(tmp_path), params)
    assert verdict["score"] == 3 and verdict["check_exit"] == 0, verdict
    assert all(verdict["hidden"].values()) and len(verdict["hidden"]) == 5
    assert (tmp_path / "tests" / "revealed").is_dir()          # the checker ran the check in a copy
    assert len(list((tmp_path / "tests" / "revealed").iterdir())) == 5


def test_t19_a_fix_that_only_fits_the_revealed_tests_fails_the_hidden_suite(tmp_path):
    params = _t19_done(tmp_path)
    (tmp_path / "ledger" / "money.py").write_text(
        "def to_cents(amount):\n"
        "    known = {'12.34': 1234, '0.125': 13, '2.675': 268, '-0.125': -13, '19.999': 2000}\n"
        "    return known.get(str(amount), int(float(amount) * 100))\n"
    )
    verdict = check_t19.check(str(tmp_path), params)
    assert verdict["score"] == 1 and verdict["hidden"]["money"] is False, verdict


def test_t19_fixed_but_never_checked_to_the_end_is_not_complete(tmp_path):
    params = fixture_t19.fixture(str(tmp_path))
    for name, source in T19_FIXED.items():
        (tmp_path / "ledger" / name).write_text(source)
    verdict = check_t19.check(str(tmp_path), params)
    assert verdict["score"] == 1 and verdict["check_exit"] == 1, verdict


@pytest.mark.parametrize("target", ["tests/run_checks.py", "tests/stages.dat"])
def test_t19_an_edited_runner_or_data_file_scores_zero(tmp_path, target):
    params = _t19_done(tmp_path)
    with open(tmp_path / target, "a") as f:
        f.write("\n")
    verdict = check_t19.check(str(tmp_path), params)
    assert verdict["score"] == 0 and verdict["changed"] == [target], verdict


def test_t19_reports_a_worker_call_that_read_the_data_file_but_not_the_check_run(tmp_path):
    run = tmp_path / "arslan-T19-r1"
    run.mkdir()
    params = _t19_done(run)
    frames = [
        {"type": "tool_call", "tool": "run_command", "args_summary": "python3 tests/run_checks.py"},
        {"type": "tool_call", "tool": "read_file", "args_summary": "ledger/money.py"},
    ]
    Path(f"{run}.frames.jsonl").write_text("".join(json.dumps(f) + "\n" for f in frames))
    assert check_t19.check(str(run), params)["data_file_read"] is False
    frames.append({"type": "tool_call", "tool": "read_file", "args_summary": "tests/stages.dat"})
    Path(f"{run}.frames.jsonl").write_text("".join(json.dumps(f) + "\n" for f in frames))
    verdict = check_t19.check(str(run), params)
    assert verdict["data_file_read"] is True and verdict["score"] == 3   # reported, not scored


# ── T20: a list that arrives in batches ───────────────────────────────────────


def _t20_summarise(run: Path) -> None:
    out = run / "summaries"
    out.mkdir(exist_ok=True)
    names = sorted(p.name for p in (run / "notes").glob("*.md"))
    for name in names:
        text = (run / "notes" / name).read_text()
        code = re.search(r"^Code word: (\S+)$", text, re.M).group(1)
        day = re.search(r"^Date: (\S+)$", text, re.M).group(1)
        (out / name).write_text(f"The note is filed under {code}. It is dated {day}.\n")
    (out / "index.md").write_text("".join(f"- {n}\n" for n in names))


def test_t20_starts_with_the_first_batch_of_six_notes_only(tmp_path):
    params = fixture_t20.fixture(str(tmp_path))
    assert _files(tmp_path) == {"inbox_check.py", "batches.dat", *(f"notes/n{i:02d}.md" for i in range(1, 7))}
    assert len(params["notes"]) == 24 and len({n["code"] for n in params["notes"].values()}) == 24
    readable = "".join(p.read_text() for p in tmp_path.rglob("*") if p.suffix in (".py", ".md"))
    assert params["notes"]["n07.md"]["code"] not in readable


def test_t20_each_batch_arrives_only_after_the_last_one_passes(tmp_path):
    fixture_t20.fixture(str(tmp_path))
    codes = []
    out = _run(tmp_path, "inbox_check.py", "--batches", "batches.dat")
    codes.append(out.returncode)
    assert out.returncode == 1 and len(list((tmp_path / "notes").iterdir())) == 6   # nothing summarised yet
    for _ in range(4):
        _t20_summarise(tmp_path)
        codes.append(_run(tmp_path, "inbox_check.py", "--batches", "batches.dat").returncode)
    assert codes == [1, 1, 1, 1, 0] and len(list((tmp_path / "notes").iterdir())) == 24


def test_t20_all_twenty_four_right_scores_three(tmp_path):
    params = fixture_t20.fixture(str(tmp_path))
    while True:
        _t20_summarise(tmp_path)
        if _run(tmp_path, "inbox_check.py", "--batches", "batches.dat").returncode == 0:
            break
    verdict = check_t20.check(str(tmp_path), params)
    assert verdict["score"] == 3 and verdict["summaries_ok"] == 24 and verdict["check_exit"] == 0, verdict


@pytest.mark.parametrize("damage", ["three_sentences", "no_code_word", "index_short", "first_batch_only"])
def test_t20_one_wrong_summary_or_a_short_index_is_not_complete(tmp_path, damage):
    params = fixture_t20.fixture(str(tmp_path))
    rounds = 1 if damage == "first_batch_only" else 4
    for _ in range(rounds):
        _t20_summarise(tmp_path)
        _run(tmp_path, "inbox_check.py", "--batches", "batches.dat")
    _t20_summarise(tmp_path)
    s = tmp_path / "summaries"
    if damage == "three_sentences":
        (s / "n09.md").write_text((s / "n09.md").read_text() + "One more.\n")
    elif damage == "no_code_word":
        (s / "n20.md").write_text("A short summary. Nothing else here.\n")
    elif damage == "index_short":
        (s / "index.md").write_text((s / "index.md").read_text().replace("- n13.md\n", ""))
    verdict = check_t20.check(str(tmp_path), params)
    assert verdict["score"] == 1, (damage, verdict)


def test_t20_an_edited_check_or_batch_file_scores_zero(tmp_path):
    params = fixture_t20.fixture(str(tmp_path))
    (tmp_path / "inbox_check.py").write_text("raise SystemExit(0)\n")
    verdict = check_t20.check(str(tmp_path), params)
    assert verdict["score"] == 0 and verdict["changed"] == ["inbox_check.py"]


# ── T21: rules revealed by the validator ──────────────────────────────────────


def _t21_clean(src: Path, *, day_first=True, rmb=True, keep="first", decimals=True) -> list[list[str]]:
    """The stand-in's own cleaner, with each rule's choice as a switch."""
    rows = list(csv.reader(src.open()))
    head, body = rows[0], rows[1:]
    if keep == "first":
        seen, kept = set(), []
        for r in body:
            if r[0] not in seen:
                seen.add(r[0])
                kept.append(r)
    elif keep == "last":
        last = {r[0]: r for r in body}
        kept = list(last.values())
    else:
        kept = body
    out = [head]
    for oid, day, customer, cur, amount in kept:
        if "/" in day:
            a, b, y = day.split("/")
            d, m = (a, b) if day_first else (b, a)
            day = f"{y}-{int(m):02d}-{int(d):02d}"
        cur = "CNY" if (rmb and cur.lower() == "rmb") else cur.upper()
        if decimals:
            amount = f"{Decimal(amount.replace(',', '.')).quantize(Decimal('0.01'), ROUND_HALF_UP)}"
        out.append([oid, day, customer, cur, amount])
    return out


def test_t21_has_three_hundred_rows_and_four_kinds_of_fault(tmp_path):
    params = fixture_t21.fixture(str(tmp_path))
    assert _files(tmp_path) == {"data/orders.csv", "validate.py", "rules.dat"}
    rows = list(csv.reader((tmp_path / "data" / "orders.csv").open()))
    head, body = rows[0], rows[1:]
    assert head == ["order_id", "order_date", "customer", "currency", "amount"] and len(body) == 300
    slashed = [r[1] for r in body if "/" in r[1]]
    assert slashed and all(
        int(d) <= 12 and int(m) <= 12 and d != m for d, m, _ in (s.split("/") for s in slashed)
    )                                                       # every slash date reads both ways
    assert any(r[3] == "rmb" for r in body) and any(r[3].islower() and r[3] != "rmb" for r in body)
    ids = [r[0] for r in body]
    assert len(ids) - len(set(ids)) >= 10
    assert any("," in r[4] for r in body) and any("." not in r[4] and "," not in r[4] for r in body)
    assert len(params["expected"]) == len(set(ids))
    text = (tmp_path / "validate.py").read_text()
    assert "rmb" not in text.lower() and "day first" not in text.lower()   # the rules are only in rules.dat


def test_t21_each_rule_is_printed_only_after_the_rules_before_it_pass(tmp_path):
    fixture_t21.fixture(str(tmp_path))
    src, out = tmp_path / "data" / "orders.csv", tmp_path / "clean" / "orders.csv"
    check = ("validate.py", "--rules", "rules.dat", "clean/orders.csv")
    steps = [
        dict(day_first=False, rmb=False, keep="all", decimals=False),
        dict(day_first=True, rmb=False, keep="all", decimals=False),
        dict(day_first=True, rmb=True, keep="all", decimals=False),
        dict(day_first=True, rmb=True, keep="first", decimals=False),
    ]
    for n, choice in enumerate(steps, 1):
        _write_csv(out, _t21_clean(src, **choice))
        res = _run(tmp_path, *check)
        assert res.returncode == 1 and f"Rule {n} of 4" in res.stdout, res.stdout
        assert f"Rule {n + 1} of 4" not in res.stdout
    _write_csv(out, _t21_clean(src))
    res = _run(tmp_path, *check)
    assert res.returncode == 0, res.stdout


def test_t21_a_clean_file_scores_three_and_keeping_the_last_duplicate_does_not(tmp_path):
    params = fixture_t21.fixture(str(tmp_path))
    out = tmp_path / "clean" / "orders.csv"
    _write_csv(out, _t21_clean(tmp_path / "data" / "orders.csv"))
    verdict = check_t21.check(str(tmp_path), params)
    assert verdict["score"] == 3 and verdict["check_exit"] == 0, verdict
    _write_csv(out, _t21_clean(tmp_path / "data" / "orders.csv", keep="last"))
    verdict = check_t21.check(str(tmp_path), params)
    assert verdict["score"] == 1 and verdict["check_exit"] == 1, verdict
    out.unlink()
    assert check_t21.check(str(tmp_path), params)["score"] == 0


@pytest.mark.parametrize("target", ["validate.py", "rules.dat"])
def test_t21_an_edited_validator_or_rules_file_scores_zero(tmp_path, target):
    params = fixture_t21.fixture(str(tmp_path))
    _write_csv(tmp_path / "clean" / "orders.csv", _t21_clean(tmp_path / "data" / "orders.csv"))
    with open(tmp_path / target, "a") as f:
        f.write("\n")
    verdict = check_t21.check(str(tmp_path), params)
    assert verdict["score"] == 0 and verdict["changed"] == [target]


# ── prompts and runner wiring ─────────────────────────────────────────────────


def test_the_goal_task_prompts_carry_their_check_line_and_name_their_files():
    prompts = json.loads((runner.HERE / "prompts.json").read_text())
    assert "{dir}/invoices" in prompts["T18"] and "{dir}/ledger.csv" in prompts["T18"]
    assert "check:" not in prompts["T18"]                  # T18's checks are Arslan's own drafted ones
    lines = {
        "T19": "check: python3 tests/run_checks.py outputs: tests/revealed/test_step_*.py",
        "T20": "check: python3 inbox_check.py --batches batches.dat",
        "T21": "check: python3 validate.py --rules rules.dat clean/orders.csv",
    }
    for task, line in lines.items():
        assert prompts[task].splitlines()[-1] == line, task
    for task in goal_tasks.GOAL_TASKS:
        prompts[task].format(dir="/r")
        assert "{dir}" in prompts[task]


def test_the_goal_tasks_are_wired_to_their_fixtures_and_checkers():
    for task in goal_tasks.GOAL_TASKS:
        assert task in runner.CHECKS and task in runner.FIXTURES, task
        assert all(task not in runner.UNSUPPORTED[w] for w in ("arslan", "arslan-legacy"))


@pytest.mark.parametrize("task", goal_tasks.GOAL_TASKS)
def test_run_one_scores_each_goal_task_from_disk(tmp_path, monkeypatch, task):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "settle", lambda *a, **k: 0.0)
    script = "import json; print(json.dumps({'end': 'done', 'final': 'all checks met'}))"
    monkeypatch.setattr(runner, "command", lambda *a, **k: ([sys.executable, "-c", script], {}))
    prompts = json.loads((runner.HERE / "prompts.json").read_text())
    rec = runner.run_one(task, "arslan", 1, prompts, "sb")
    assert rec["check"]["score"] == 0 and not rec["passed"], rec["check"]   # the reply's claim counts for nothing


def test_per_task_repeats_give_the_goal_tasks_six_and_the_others_three():
    assert [goal_tasks.repeats_for(t, "per-task") for t in ("T18", "T21", "T1", "T17")] == [6, 6, 3, 3]
    assert goal_tasks.repeats_for("T18", "3") == 3 and goal_tasks.repeats_for("T1", "1") == 1
    with pytest.raises(ValueError):
        goal_tasks.repeats_for("T1", "many")


def test_the_runner_interleaves_tasks_and_stops_each_at_its_own_k(monkeypatch):
    seen = []
    monkeypatch.setattr(
        runner, "run_one", lambda task, who, n, *a, **k: seen.append((task, n)) or {
            "run": "x", "model": "m", "passed": False, "rc": 0, "check": {}, "usage": {"usd_peak": 0, "span_s": 0}}
    )
    monkeypatch.setattr(runner, "sandbox_profile", lambda: "sb")
    monkeypatch.setattr(sys, "argv", ["runner", "--tasks", "T1,T19", "--entrants", "arslan", "--repeats", "per-task"])
    runner.main()
    assert [n for t, n in seen if t == "T19"] == [1, 2, 3, 4, 5, 6]
    assert [n for t, n in seen if t == "T1"] == [1, 2, 3]
    assert seen[:4] == [("T1", 1), ("T19", 1), ("T1", 2), ("T19", 2)]


def test_the_record_keeps_the_drivers_goal_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "settle", lambda *a, **k: 0.0)
    goal = {"setting": "on", "flagged": 1, "round": 3, "status": "complete"}
    script = f"import json; print(json.dumps({{'end': 'done', 'final': 'x', 'goal': {goal!r}}}))"
    monkeypatch.setattr(runner, "command", lambda *a, **k: ([sys.executable, "-c", script], {}))
    rec = runner.run_one("T17", "arslan", 1, {"T17": "add {dir}"}, "sb")
    assert rec["goal"] == goal
    monkeypatch.setattr(runner, "command", lambda *a, **k: ([sys.executable, "-c", "print('{}')"], {}))
    assert runner.run_one("T17", "arslan", 2, {"T17": "add {dir}"}, "sb")["goal"] is None


# ── the driver: BENCH_GOAL ────────────────────────────────────────────────────


def test_bench_goal_turns_the_setting_on_by_its_key_and_only_bench_goal_can(monkeypatch):
    monkeypatch.delenv("BENCH_ARSLAN_SETTINGS", raising=False)
    monkeypatch.delenv("BENCH_SHELL_POLICY", raising=False)
    monkeypatch.delenv("BENCH_GOAL", raising=False)
    assert "goal_mode" not in arslan_driver.settings_body("/run")
    monkeypatch.setenv("BENCH_GOAL", "1")
    assert arslan_driver.settings_body("/run")["goal_mode"] == "true"
    monkeypatch.delenv("BENCH_GOAL")
    monkeypatch.setenv("BENCH_ARSLAN_SETTINGS", '{"goal_mode": "true"}')
    with pytest.raises(ValueError):
        arslan_driver.settings_body("/run")


class _Settings:
    """A stand-in for the instance's settings API: main ignores goal_mode (its schema drops unknown keys),
    an instance may refuse it, and the build branch keeps it."""

    def __init__(self, mode: str):
        self.mode, self.stored, self.puts = mode, {}, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _resp(self, status=200, data=None):
        class R:
            status_code = status

            def json(self):
                return data

            def raise_for_status(self):
                if status >= 400:
                    raise RuntimeError(status)
        return R()

    def get(self, url):
        if url.endswith("/provider-configs"):
            return self._resp(200, [])
        return self._resp(200, dict(self.stored))

    def post(self, url, json):
        return self._resp(200, {"id": 1})

    def patch(self, url):
        return self._resp(200, {})

    def put(self, url, json):
        self.puts.append(dict(json))
        if "goal_mode" in json and self.mode == "refuses":
            return self._resp(422, {})
        body = {k: v for k, v in json.items() if self.mode == "keeps" or k != "goal_mode"}
        self.stored.update(body)
        return self._resp(200, body)


@pytest.mark.parametrize("mode, setting", [("keeps", "on"), ("ignores", "absent"), ("refuses", "refused")])
def test_configure_says_whether_the_instance_took_goal_mode_and_never_fails_on_main(monkeypatch, mode, setting):
    monkeypatch.delenv("BENCH_ARSLAN_SETTINGS", raising=False)
    monkeypatch.delenv("BENCH_SHELL_POLICY", raising=False)
    monkeypatch.setenv("BENCH_GOAL", "1")
    api = _Settings(mode)
    policy, goal = arslan_driver.configure("http://x/api/v1", "/run", "http://p", "m", client=api)
    assert (policy, goal) == ("ask_risky", setting)
    assert api.stored["workspace_dir"] == "/run"           # the rest of the settings still went in
    monkeypatch.delenv("BENCH_GOAL")
    assert arslan_driver.configure("http://x/api/v1", "/run", "http://p", "m", client=_Settings(mode))[1] is None


class _GoalArslan:
    """A fake instance with goal mode: `/goal <objective>` gets a host line (no stream_end when `bare`), and
    `/goal start confirm` a host line and then a background job, whose frames carry the goal's checks."""

    def __init__(self, run_dir: Path, *, bare=False, flagged=True, goal_on=True):
        self.run_dir, self.bare, self.flagged, self.goal_on = run_dir, bare, flagged, goal_on
        self.sent, self.queue = [], [{"type": "history"}]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        if msg["type"] != "user_message":
            return
        text = msg["content"]
        if not self.goal_on:
            (self.run_dir / "out.txt").write_text(text)
            self.queue += [{"type": "stream_chunk", "content": "plain"}, {"type": "stream_end"}]
        elif text.startswith("/goal start confirm"):
            checks = [{"id": "c1", "user_confirmed": False}, {"id": "c2", "user_confirmed": self.flagged}]
            self.queue += [
                {"type": "message", "role": "assistant", "content": "Goal started."},
                {"type": "job_update", "job_id": "j1", "phase": "running", "goal": "x",
                 "goal_state": {"status": "active", "round": 1, "checks": checks}},
                {"type": "job_update", "job_id": "j1", "phase": "running", "goal": "x",
                 "goal_state": {"status": "active", "round": 2, "checks": checks}},
                {"type": "job_update", "job_id": "j1", "phase": "finished", "outcome": "done", "goal": "x",
                 "goal_state": {"status": "complete", "round": 2, "checks": checks}},
            ]
            (self.run_dir / "out.txt").write_text("done")
        elif text.startswith("/goal "):
            self.queue.append({"type": "message", "role": "assistant", "content": "Goal set. Check the checks."})
            if not self.bare:
                self.queue.append({"type": "stream_end"})

    async def recv(self):
        if not self.queue:
            await asyncio.sleep(10)
        return json.dumps(self.queue.pop(0))


def _drive(tmp_path, fake, prompts, goal, **kw):
    run_dir = fake.run_dir
    return asyncio.run(arslan_driver.run(
        "http://x/api/v1", str(run_dir), prompts, str(tmp_path / "frames.jsonl"),
        connect=lambda *a, **k: fake, idle_after_s=0, recv_timeout=0.01, goal=goal, **kw))


def test_a_goal_run_sends_the_objective_then_start_confirm_and_waits_for_the_job(tmp_path):
    run_dir = tmp_path / "arslan-T18-r1"
    run_dir.mkdir()
    fake = _GoalArslan(run_dir)
    out = _drive(tmp_path, fake, ["sort the invoices"], "on")
    users = [m["content"] for m in fake.sent if m["type"] == "user_message"]
    assert users == ["/goal sort the invoices", "/goal start confirm"]
    assert out["end"] == "done" and (run_dir / "out.txt").read_text() == "done"
    assert out["goal"] == {"setting": "on", "flagged": 1, "round": 2, "status": "complete"}


def test_a_goal_with_no_flagged_check_counts_zero_and_unseen_checks_count_as_unknown(tmp_path):
    run_dir = tmp_path / "arslan-T18-r1"
    run_dir.mkdir()
    assert _drive(tmp_path, _GoalArslan(run_dir, flagged=False), ["x"], "on")["goal"]["flagged"] == 0
    fake = _GoalArslan(run_dir, goal_on=False)          # main: /goal is plain text, nothing shows the checks
    out = _drive(tmp_path, fake, ["x"], "absent")
    assert [m["content"] for m in fake.sent if m["type"] == "user_message"] == ["/goal x", "/goal start confirm"]
    assert out["goal"] == {"setting": "absent", "flagged": None, "round": None, "status": None}
    assert out["end"] == "done"


def test_a_host_line_without_stream_end_still_ends_the_goal_setting_turn(tmp_path):
    run_dir = tmp_path / "arslan-T18-r1"
    run_dir.mkdir()
    fake = _GoalArslan(run_dir, bare=True)
    out = _drive(tmp_path, fake, ["x"], "on", goal_quiet_s=0.2)
    assert [m["content"] for m in fake.sent if m["type"] == "user_message"] == ["/goal x", "/goal start confirm"]
    assert out["end"] == "done" and out["goal"]["status"] == "complete"


def test_each_turn_of_a_multi_turn_task_is_sent_as_its_own_goal_and_snapshotted_after_it(tmp_path):
    run_dir = tmp_path / "arslan-T8-r1"
    run_dir.mkdir()
    fake = _GoalArslan(run_dir)
    out = _drive(tmp_path, fake, ["write", "shorten"], "on")
    users = [m["content"] for m in fake.sent if m["type"] == "user_message"]
    assert users == ["/goal write", "/goal start confirm", "/goal shorten", "/goal start confirm"]
    assert out["turns"] == 2 and (tmp_path / "arslan-T8-r1.turn1").is_dir()
    assert not (tmp_path / "arslan-T8-r1.turn2").exists()


def test_without_bench_goal_the_prompts_go_as_they_are(tmp_path):
    run_dir = tmp_path / "arslan-T18-r1"
    run_dir.mkdir()
    fake = _GoalArslan(run_dir, goal_on=False)
    out = _drive(tmp_path, fake, ["sort the invoices"], None)
    assert [m["content"] for m in fake.sent if m["type"] == "user_message"] == ["sort the invoices"]
    assert "goal" not in out


# ── report: the completion bar ────────────────────────────────────────────────

OTHER = goal_tasks.OTHER_TASKS


def _arm(round_name, goal_done, other_done, *, goal=None, looks=1, end="done"):
    """Records for one arm: `goal_done` of the 24·looks goal-task runs and `other_done` of the 39·looks other
    runs complete (checker score 3); the rest score 1."""
    recs = []
    pools = [(goal_tasks.GOAL_TASKS, 6 * looks, goal_done), (OTHER, 3 * looks, other_done)]
    for tasks, k, done in pools:
        i = 0
        for task in tasks:
            for n in range(1, k + 1):
                score = 3 if i < done else 1
                i += 1
                recs.append({"task": task, "entrant": "arslan", "repeat": n, "model": "deepseek-v4-pro",
                             "run": f"arslan-{task}-r{n}-{round_name}", "check": {"score": score},
                             "passed": score == 3 and end == "done", "end": end, "goal": goal,
                             "usage": {"usd_peak": 0.1, "span_s": 1.0, "model_calls": 1}})
    return recs


ON = {"setting": "on", "flagged": 0, "round": 1, "status": "complete"}


@pytest.mark.parametrize(
    "off_goal, on_goal, off_other, on_other, passes",
    [
        (10, 18, 30, 27, True),     # exactly +8 and exactly -3
        (10, 17, 30, 30, False),    # +7 is short of the gain
        (10, 18, 30, 26, False),    # -4 is past the tolerance
        (0, 24, 39, 39, True),
    ],
)
def test_the_bar_needs_eight_more_goal_runs_and_at_most_three_fewer_others(off_goal, on_goal, off_other, on_other,
                                                                           passes):
    bar = report.completion_bar(_arm("off", off_goal, off_other), _arm("on", on_goal, on_other, goal=ON))
    assert bar["judged"], bar
    assert bar["pass"] is passes, bar
    assert (bar["goal"]["off"], bar["goal"]["on"], bar["other"]["off"], bar["other"]["on"]) == (
        off_goal, on_goal, off_other, on_other)


def test_the_pooled_rerun_doubles_both_thresholds():
    off, on = _arm("off", 10, 60, looks=2), _arm("on", 26, 54, goal=ON, looks=2)
    bar = report.completion_bar(off, on)
    assert bar["looks"] == 2 and bar["pass"], bar
    assert not report.completion_bar(off, _arm("on", 25, 54, goal=ON, looks=2))["pass"]
    assert not report.completion_bar(off, _arm("on", 26, 53, goal=ON, looks=2))["pass"]


def test_complete_means_the_checker_passed_whatever_the_run_or_the_goal_said():
    off = _arm("off", 10, 30, end="task_waiting_user")    # ended waiting: still complete by its checker
    on = _arm("on", 18, 27, goal=ON)
    for r in on:
        if r["task"] == "T19" and r["check"]["score"] == 1:
            r["end"] = "done"                             # said done, checker failed
    bar = report.completion_bar(off, on)
    assert bar["goal"]["off"] == 10 and bar["pass"]
    assert bar["claimed_not_checked"] == sum(1 for r in on if r["check"]["score"] != 3)


@pytest.mark.parametrize("why", ["missing_run", "on_without_goal", "off_with_goal", "one_look_and_a_half"])
def test_the_bar_is_not_judged_on_arms_that_do_not_match(why):
    off, on = _arm("off", 10, 30), _arm("on", 18, 27, goal=ON)
    if why == "missing_run":
        on = on[1:]
    elif why == "on_without_goal":
        on[0]["goal"] = {"setting": "absent", "flagged": None, "round": None, "status": None}
    elif why == "off_with_goal":
        off[0]["goal"] = ON
    else:
        off, on = off + _arm("off2", 0, 0)[:30], on + _arm("on2", 0, 0, goal=ON)[:30]
    bar = report.completion_bar(off, on)
    assert not bar["judged"] and not bar["pass"] and bar["why"], bar


def test_the_bar_reports_flagged_runs_and_runs_where_the_flag_could_not_be_seen():
    on = _arm("on", 18, 27, goal=ON)
    on[0]["goal"] = dict(ON, flagged=2)
    on[1]["goal"] = dict(ON, flagged=None)
    bar = report.completion_bar(_arm("off", 10, 30), on)
    assert (bar["flagged_runs"], bar["flag_unseen_runs"]) == (1, 1)
    text = report.render_bar(bar)
    assert "1.47%" in text and "1.31%" in text and "PASS" in text


def test_the_report_cli_prints_the_bar_for_the_named_rounds(tmp_path):
    recs = _arm("r64-l7-off", 10, 30) + _arm("r64-l7-on", 18, 27, goal=ON)
    path = tmp_path / "results.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in recs))
    out = subprocess.run(
        [sys.executable, "-m", "scripts.kernel_bench.report", str(path), "--bar",
         "--off-round", "r64-l7-off", "--on-round", "r64-l7-on"],
        capture_output=True, text=True, cwd=runner.HERE.parents[1], check=True,
    ).stdout
    assert "Completion bar" in out and "PASS" in out and "18/24" in out


def test_the_existing_report_cli_still_reads_round_and_path(tmp_path):
    recs = _arm("r64-l7-off", 10, 30)
    path = tmp_path / "results.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in recs))
    out = subprocess.run(
        [sys.executable, "-m", "scripts.kernel_bench.report", "--round", "r64-l7-off", str(path), "--offpeak"],
        capture_output=True, text=True, cwd=runner.HERE.parents[1], check=True,
    ).stdout
    assert "| T18 | arslan" in out and "| T1 | arslan" in out and "Completion bar" not in out


def test_goal_task_helpers_round_trip_and_find_python3(tmp_path):
    data = {"a": [1, "é"]}
    assert goal_tasks.decode(goal_tasks.encode(data)) == data
    assert Path(PY).name.startswith("python3")
    shutil.which(PY)
