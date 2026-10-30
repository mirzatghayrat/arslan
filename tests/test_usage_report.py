"""0.1.62 M2: the weekly usage report reads a synthetic DB read-only and prints numbers only.

Every table holds only the columns the script reads, plus free-text columns seeded with
"SECRET" strings it must never print. Runs are mostly 'host' (chat turns, fires and background jobs since
2026-09-14), with an old 'scheduled' and an old 'live' one; a 'replay' and a 'worker' run are there to be
left out. Rows sit on Wednesday noon UTC, so the week they
fall in is the same in every time zone; the one local-time test sets TZ itself.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import date

import pytest

from scripts import usage_report

SCHEMA = """
CREATE TABLE runs (id INTEGER PRIMARY KEY, kind TEXT, started_at TEXT, user_message TEXT,
                   error_kind TEXT, error_text TEXT);
CREATE TABLE run_steps (id INTEGER PRIMARY KEY, run_id INTEGER, kind TEXT, ref TEXT,
                        detail TEXT, duration_ms INTEGER);
CREATE TABLE companion_tasks (id TEXT PRIMARY KEY, phase TEXT, pause_reason TEXT, created_at TEXT);
CREATE TABLE approval_events (id INTEGER PRIMARY KEY, created_at TEXT, kind TEXT, target TEXT,
                              detail TEXT, decided_by TEXT, decision TEXT, extra TEXT);
CREATE TABLE judgments (id INTEGER PRIMARY KEY, point TEXT, state TEXT, outcome TEXT,
                        created_at TEXT);
CREATE TABLE conversation_events (id INTEGER PRIMARY KEY, kind TEXT, ref TEXT, summary TEXT,
                                  created_at TEXT);
CREATE TABLE usage_ledger (id INTEGER PRIMARY KEY, ts TEXT, scope TEXT, model TEXT);
CREATE TABLE tools (key TEXT PRIMARY KEY, toolset_key TEXT);
"""
A = "2026-09-30 12:00:00.000000"    # Wednesday, week of Monday 2026-09-28
B = "2026-10-07 12:00:00.123456"    # Wednesday, week of Monday 2026-10-05
BEFORE, AFTER = "2026-09-23 12:00:00", "2026-10-14 12:00:00"
WEEK_A, WEEK_B = "2026-09-28 – 2026-10-04", "2026-10-05 – 2026-10-11"
WINDOW = ["--since", "2026-09-30", "--weeks", "2"]     # a Wednesday: snaps back to Monday

ANTHROPIC_400 = ("Model request failed (input HTTP 400): Client error '400 Bad Request' "
                 "{\"error\":{\"message\":\"tools.137.custom.input_schema: input_schema does "
                 "not support oneOf, allOf, or anyOf at the top level\"}} SECRET-ERROR. Tried 1.")
DEEPSEEK_400 = ("Model request failed (input HTTP 400): Invalid schema for function "
                "'mcp_6__secret_capture': '^[^=]+$' is not a regex. Tried 1 attempt.")
OTHER_400 = "Model request failed (input HTTP 400): max_tokens too large SECRET. Tried 1."
RATE_429 = "Model request failed (rate HTTP 429): tools.3 slow down SECRET. Tried 3."
CUT = "tool 'run_command' timed out"
OUTER = "stopped by the time limit; no output was captured"


def _ref(tool, ok):
    return json.dumps({"tool": tool, "ok": ok})


def _detail(error):
    return json.dumps({"args_summary": "SECRET-ARGS", "summary": "SECRET-SUMMARY",
                       "target": "/Users/SECRET-PATH/Finder.app", "error": error,
                       "args_full": "{\"command\": \"rm -rf /Users/SECRET-PATH\"}",
                       "result_raw": "SECRET-RESULT"})


def make_db(path, *, wal=False, keep_open=False):
    """The synthetic DB. wal: journal_mode=WAL, like the app (server/db/session.py:29);
    keep_open: return the writer still open with its WAL not checkpointed (the app running)."""
    con = sqlite3.connect(path)
    if wal:
        con.execute("PRAGMA journal_mode=WAL")
    if keep_open:
        con.execute("PRAGMA wal_autocheckpoint=0")
    con.executescript(SCHEMA)
    # registered tools: a seeded catalog tool that is not a built-in executor, and an MCP tool
    con.executemany("INSERT INTO tools VALUES (?, ?)", [
        ("todo", "hermes_core"), ("web_search", "web"), ("mcp_6__inspect_page", "mcp_6")])
    runs = [(1, "host", A, None, None),
            (2, "host", A, "HostError", ANTHROPIC_400),      # a chat turn: the error frame's text
            (3, "live", A, "ModelCallError", DEEPSEEK_400),  # a chat turn before 2026-09-14
            (4, "scheduled", A, "HostError", OTHER_400), (13, "host", A, "HostError", RATE_429),
            (5, "replay", A, "ModelCallError", ANTHROPIC_400),   # the gate's evidence: never counted
            (11, "worker", A, "HostError", ANTHROPIC_400),       # a helper run: never counted
            (6, "host", B, "HostError", DEEPSEEK_400), (7, "host", B, None, None),
            (8, "host", B, "RuntimeError", ANTHROPIC_400),
            (12, "host", B, "HostError", "Stopped: HTTP 400 tools.3 input_schema SECRET"),  # no model call
            (9, "host", BEFORE, None, None), (10, "host", AFTER, "HostError", ANTHROPIC_400)]
    con.executemany("INSERT INTO runs VALUES (?, ?, ?, 'SECRET-USER-MESSAGE', ?, ?)", runs)
    steps = [  # (run, kind, tool, ok, error, ms)
        (1, "tool_call", "read_file", True, None, 40),
        (1, "tool_call", "read_file", False, "SECRET-ERROR no such file", 40),
        (1, "tool_call", "todo", True, None, 30),                    # registered via `tools`
        (1, "tool_call", "mcp_6__inspect_page", True, None, 900),
        (1, "tool_call", "mcp_6__secret_tool_name", False, "SECRET-ERROR", 900),
        (1, "tool_call", "mcp_12__fetch", False, "SECRET-ERROR", 900),
        (1, "tool_call", "run_command", False, CUT, 20004),
        (1, "tool_call", "run_command", False, "stopped after 120 s", 120050),
        (1, "tool_call", "run_command", False, "exit code 1", 300),
        (1, "tool_call", "run_command", True, None, 20000),          # ok: not a cut
        (1, "route", "read_file", False, None, 10),                  # not a tool call
        (1, "escalation", "run_command", False, CUT, 20000),         # not a tool call
        (5, "tool_call", "run_command", False, CUT, 20000),          # replay run
        (11, "tool_call", "run_command", False, OUTER, 600000),      # helper run
        (11, "tool_call", "mcp_6__inspect_page", False, "SECRET", 900),
        (7, "tool_call", "run_command", False, OUTER, 615000),
        (7, "tool_call", "run_command", False, CUT, 19800),
        (7, "tool_call", "web_search", True, None, 2000),
        (7, "tool_call", "Open SECRET.app /Users/SECRET-PATH", False, "SECRET", 10),
        (7, "tool_call", "read_tax_2025", False, "SECRET unknown tool", 5),   # model-invented
        (10, "tool_call", "run_command", False, CUT, 20000),         # after the window
    ]
    con.executemany("INSERT INTO run_steps (run_id, kind, ref, detail, duration_ms) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [(r, k, _ref(t, ok), _detail(e), ms) for r, k, t, ok, e, ms in steps])
    tasks = [("t1", "succeeded", None, A),
             ("t2", "waiting_user", "task_reconciliation_required", A),
             ("t3", "waiting_user", "acceptance_review_required", A),
             ("t4", "failed", "task_no_progress", A),                  # stopped, not waiting
             ("t5", "waiting_user", "Check /Users/SECRET-PATH first", A),
             ("t6", "waiting_user", "task_reconciliation_required", B),
             ("t7", "succeeded", None, B), ("t8", "succeeded", None, B), ("t9", "running", None, B),
             ("t10", "waiting_user", "task_input_required", BEFORE)]
    con.executemany("INSERT INTO companion_tasks VALUES (?, ?, ?, ?)", tasks)
    cards = [(A, "command", "user"), (A, "command", "expired"), (A, "mcp", "user"),
             (A, "command", "rule"), (A, "command", "grant"), (A, "file", "floor"),
             (A, "command", "away"), (B, "command", "user"), (B, "command", "policy"),
             (AFTER, "command", "user")]
    con.executemany("INSERT INTO approval_events (created_at, kind, target, detail, decided_by, "
                    "decision) VALUES (?, ?, '/Applications/SECRET.app', 'SECRET-DETAIL', ?, "
                    "'allow')", cards)

    def state(rule, sandboxed):
        return json.dumps({"tool": "run_command", "command": "curl SECRET-COMMAND", "rule": rule,
                           "reason": "SECRET-REASON", "sandboxed": sandboxed,
                           "user_request": "SECRET-REQUEST"})
    judged = [("tool.approval", state("", False), "approved", A),
              ("tool.approval", state("apple-events", None), "declined", A),
              ("reply.should_continue", state("", None), "followed", A),
              ("tool.approval", state("", False), "expired", B),
              ("tool.approval", state("git-push", None), None, B)]
    con.executemany("INSERT INTO judgments (point, state, outcome, created_at) VALUES (?, ?, ?, ?)",
                    judged)
    events = [("mcp_schema_relaxed", B), ("mcp_schema_relaxed", B), ("memory", B),
              ("mcp_schema_relaxed", AFTER)]
    con.executemany("INSERT INTO conversation_events (kind, ref, summary, created_at) VALUES "
                    "(?, '{\"tool_key\": \"mcp_6__secret_mcp_tool\"}', 'SECRET-SUMMARY', ?)",
                    events)
    ledger = [(A, "memory_facts")] * 3 + [(A, "memory"), (A, "answer"), (A, "answer"),
                                          (A, "judge"), (B, "memory_facts"), (AFTER, "memory")]
    con.executemany("INSERT INTO usage_ledger (ts, scope, model) VALUES (?, ?, 'secret-model')",
                    ledger)
    con.commit()
    if keep_open:
        return con          # left open, WAL not checkpointed: the app is still running
    con.close()
    return None


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "Application Support" / "arslan.db"      # a space, like the macOS default
    path.parent.mkdir()
    make_db(path)
    return path


def collect(path):
    con = usage_report.connect_ro(path)
    try:
        return usage_report.collect(con, usage_report.week_starts(date(2026, 10, 18), 2,
                                                                  date(2026, 9, 30)))
    finally:
        con.close()


def run(path, capsys, *extra):
    assert usage_report.main(["--db", str(path), *WINDOW, *extra]) == 0
    return capsys.readouterr().out


def table(out, heading):
    """The Markdown table right under `heading`, as rows of cells (header row first)."""
    lines = out.splitlines()
    rows = []
    for line in lines[lines.index(heading) + 1:]:
        if line.startswith("|"):
            if not line.startswith("|---"):
                rows.append([cell.strip() for cell in line.strip("|").split("|")])
        elif rows:
            break
    return rows


def row(rows, label):
    return next(r[1:] for r in rows if r[0] == label)


def test_weeks_are_monday_to_sunday_and_since_snaps_back():
    assert usage_report.week_starts(date(2026, 10, 18), 4, None) == [
        date(2026, 9, 21), date(2026, 9, 28), date(2026, 10, 5), date(2026, 10, 12)]
    assert usage_report.week_starts(date(2026, 10, 18), 2, date(2026, 9, 30)) == [
        date(2026, 9, 28), date(2026, 10, 5)]
    # --since without --weeks runs through the current week
    assert usage_report.week_starts(date(2026, 10, 18), None, date(2026, 10, 1)) == [
        date(2026, 9, 28), date(2026, 10, 5), date(2026, 10, 12)]


def test_runs_tasks_and_waiting_reasons(db):
    data = collect(db)
    weekly = data["weekly"]
    # the user's runs (host, the old scheduled and live): not the replay arm, not the helper run,
    # and not the runs outside the window
    assert [w["runs"] for w in weekly] == [5, 4]
    assert [(w["tasks"], w["waiting"]) for w in weekly] == [(5, 3), (4, 1)]
    # only tasks waiting on the user; free text is never printed as a reason
    assert data["waiting_reasons"] == {
        "task_reconciliation_required": [1, 1], "acceptance_review_required": [1, 0],
        "other": [1, 0]}


def test_tool_failures_fold_mcp_and_skip_other_step_kinds(db):
    data = collect(db)
    weekly = data["weekly"]
    assert [(w["calls"], w["failed"]) for w in weekly] == [(10, 6), (5, 4)]
    assert [(w["mcp_calls"], w["mcp_failed"]) for w in weekly] == [(3, 2), (0, 0)]
    # a name prints only when the product registered it (built-in list or the `tools` table);
    # the free-text name and the model-invented `read_tax_2025` are both `other`
    assert data["tools"] == {"mcp": [(3, 2), (0, 0)], "read_file": [(2, 1), (0, 0)],
                             "todo": [(1, 0), (0, 0)], "run_command": [(4, 3), (2, 2)],
                             "web_search": [(0, 0), (1, 0)], "other": [(0, 0), (2, 2)]}


def test_the_report_counts_the_run_kinds_the_usage_page_counts():
    """One constant for both (server/run_kinds.py): the report counted only 'live' for weeks after chat
    turns became 'host', and every run-based table read 0."""
    from server.api import usage
    assert usage._RUN_KINDS is usage_report.USER_RUN_KINDS


def test_a_chat_turn_is_recorded_under_a_kind_the_report_counts():
    """Chat turns, scheduled fires (Arslan turns since C1) and background jobs all go through
    host_run.execute's default kind."""
    import inspect
    from server.services import host_run
    assert inspect.signature(host_run.execute).parameters["kind"].default in usage_report.USER_RUN_KINDS
    assert "replay" not in usage_report.USER_RUN_KINDS and "worker" not in usage_report.USER_RUN_KINDS


async def test_a_schema_refusal_on_a_chat_turn_is_counted_from_the_products_own_text(tmp_path):
    """The text a host run stores for a provider's tool-schema refusal is the error frame's message
    (host_run.py:71); built here by the product itself, so the report and the product cannot drift."""
    from server.orchestrator import llm_errors, model_call
    texts = []
    for excerpt in ("tools.0.custom.input_schema: input_schema does not support anyOf",
                    "Invalid schema for function 'mcp_3__find': '^[a-z]+$' is not a regex"):
        exc = model_call.ModelCallError("input", status=400, excerpt=excerpt, attempts=1, waited_s=0,
                                        recoveries=[])
        texts.append((await llm_errors.error_frame(exc))["message"])
    path = tmp_path / "arslan.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO runs (kind, started_at, error_kind, error_text) VALUES ('host', ?, "
                    "'HostError', ?)", [(A, text) for text in texts])
    con.commit()
    con.close()
    assert [w["mcp_turns_by_text"] for w in collect(path)["weekly"]] == [2, 0]


def test_the_built_in_tool_list_covers_every_executor():
    """A built-in tool missing from BUILT_IN_TOOLS would print as `other`: add it there."""
    from server.registry.executors import EXECUTORS
    assert set(EXECUTORS) <= usage_report.BUILT_IN_TOOLS


def test_run_command_time_limits_by_fixed_text_and_by_duration(db):
    weekly = collect(db)["weekly"]
    got = [(w["rc_failed"], w["rc_cut"], w["rc_own_limit"], w["rc_outer_limit"], w["rc_cut_by_ms"])
           for w in weekly]
    assert got == [(3, 1, 1, 0, 1), (2, 1, 0, 1, 1)]


def test_mcp_whole_turn_failures_by_text_and_by_event(db):
    weekly = collect(db)["weekly"]
    # HTTP 400 with a tool-schema shape, on a run that failed on a model call: the old live run's
    # ModelCallError and a host run's HostError with ModelCallError's text both count; a HostError
    # with other text, a replay and a helper run don't
    assert [w["mcp_turns_by_text"] for w in weekly] == [2, 1]
    assert [w["mcp_relaxed"] for w in weekly] == [0, 2]


def test_cards_come_from_the_ledger_and_the_shadow_judgments_are_not_read(db):
    """C4 removed the command cards' shadow judgment: its old judgments rows (still in the fixture,
    as in a database that has not pruned them yet) are no longer counted anywhere."""
    data = collect(db)
    weekly = data["weekly"]
    assert [(w["cards_shown"], w["cards_auto"]) for w in weekly] == [(3, 4), (1, 1)]
    assert data["shown_by_kind"] == {"command": [2, 1], "mcp": [1, 0]}
    assert "judged_cards" not in weekly[0] and "judged_kind" not in data and "judged_outcome" not in data


def test_post_turn_calls_come_from_the_usage_ledger(db):
    weekly = collect(db)["weekly"]
    assert [(w["memory_facts"], w["memory"]) for w in weekly] == [(3, 1), (1, 0)]


def test_the_printed_tables(db, capsys):
    out = run(db, capsys)
    assert WEEK_A in out and WEEK_B in out and "2026-10-12" not in out
    cards = table(out, "## Cards")
    assert cards[0][1:] == ["Ledger: cards shown", "Ledger: auto-decided"]
    assert row(cards, WEEK_A) == ["3", "4"]
    assert row(table(out, "## Runs and tasks"), WEEK_A) == ["5", "5", "3", "60%"]
    assert row(table(out, "## Tool calls"), WEEK_B) == ["5", "4", "80%", "0", "0"]
    assert row(table(out, "## run_command time limits"), WEEK_A) == ["3", "1", "1", "0", "≈1"]
    assert row(table(out, "## MCP whole-turn failures"), WEEK_B) == ["≈1", "2"]
    assert row(table(out, "## Post-turn model calls"), WEEK_A) == ["3", "1"]
    assert row(table(out, "### Tool calls by tool (failed/calls)"), "mcp") == ["2/3", "0/0"]
    assert row(table(out, "### Waiting on you, by reason"), "other") == ["1", "0"]
    assert "Command cards in judgments" not in out


def test_nothing_but_numbers_and_fixed_codes_leaks(db, capsys):
    out = run(db, capsys)
    # paths, commands, app names, error text, arguments, MCP tool names, rules, the DB's folder
    assert "secret" not in out.lower()
    for text in ("Finder", "/Users", "/Applications", "rm -rf", "curl", "anyOf", "top level",
                 "tools.137", "inspect_page", "mcp_6", "mcp_12", "apple-events", "git-push",
                 "Application Support", "read_tax_2025", "tax"):
        assert text not in out


def test_the_database_file_is_never_written(db, capsys):
    before = os.stat(db)
    listing = sorted(p.name for p in db.parent.iterdir())
    run(db, capsys)
    after = os.stat(db)
    assert (after.st_mtime_ns, after.st_size) == (before.st_mtime_ns, before.st_size)
    assert sorted(p.name for p in db.parent.iterdir()) == listing      # no journal, no WAL
    con = usage_report.connect_ro(db)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            con.execute("INSERT INTO runs (kind, started_at) VALUES ('live', ?)", (A,))
    finally:
        con.close()


def test_a_closed_wal_database_gains_no_side_files(tmp_path, capsys):
    """The app closed: its WAL database has no -wal/-shm. A plain mode=ro reader would create
    both and leave them behind; the report must leave the folder exactly as it found it."""
    path = tmp_path / "arslan.db"
    make_db(path, wal=True)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["arslan.db"]   # the app is closed
    before = os.stat(path)
    out = run(path, capsys)
    assert row(table(out, "## Runs and tasks"), WEEK_A)[0] == "5"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["arslan.db"]
    after = os.stat(path)
    assert (after.st_mtime_ns, after.st_size) == (before.st_mtime_ns, before.st_size)


def test_reads_a_wal_database_while_the_app_holds_it_open(tmp_path, capsys):
    path = tmp_path / "arslan.db"
    writer = make_db(path, wal=True, keep_open=True)
    try:
        listing = sorted(p.name for p in tmp_path.iterdir())
        before = os.stat(path)
        wal = os.stat(f"{path}-wal").st_size
        out = run(path, capsys)
        assert row(table(out, "## Runs and tasks"), WEEK_A)[0] == "5"     # rows still in the WAL
        assert os.stat(path).st_mtime_ns == before.st_mtime_ns          # no checkpoint
        assert os.stat(f"{path}-wal").st_size == wal
        assert sorted(p.name for p in tmp_path.iterdir()) == listing
        con = usage_report.connect_ro(path)       # not immutable here: mode=ro must refuse
        try:
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                con.execute("INSERT INTO runs (kind, started_at) VALUES ('live', ?)", (A,))
        finally:
            con.close()
    finally:
        writer.close()


def test_default_path_follows_the_server_rule_without_creating_anything(db, tmp_path, monkeypatch,
                                                                        capsys):
    monkeypatch.setenv("ARSLAN_DB_PATH", str(db))
    assert usage_report.default_db() == db
    assert usage_report.main(WINDOW) == 0
    assert WEEK_A in capsys.readouterr().out
    monkeypatch.delenv("ARSLAN_DB_PATH")
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path / "fresh"))
    assert usage_report.default_db() == (tmp_path / "fresh").resolve() / "arslan.db"
    assert usage_report.main(WINDOW) == 2                   # no database: says so, creates nothing
    assert not (tmp_path / "fresh").exists()


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="needs time.tzset")
def test_weeks_are_cut_at_local_midnight(tmp_path, monkeypatch):
    path = tmp_path / "arslan.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    # Sunday 20:00 UTC is already Monday 04:00 in Shanghai (UTC+8, no DST)
    con.execute("INSERT INTO runs (kind, started_at) VALUES ('live', '2026-10-04 20:00:00')")
    con.commit()
    con.close()
    try:
        monkeypatch.setenv("TZ", "UTC")
        time.tzset()
        assert [w["runs"] for w in collect(path)["weekly"]] == [1, 0]
        monkeypatch.setenv("TZ", "Asia/Shanghai")
        time.tzset()
        assert [w["runs"] for w in collect(path)["weekly"]] == [0, 1]
    finally:
        monkeypatch.undo()
        time.tzset()


def test_the_report_loads_nothing_of_the_server_but_the_run_kinds():
    """It runs read-only against the user's real database: importing it must not build the settings,
    the secret bootstrap or anything else (server.config); only the import-free constant module."""
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    code = ("import sys, scripts.usage_report; "
            "print(sorted(m for m in sys.modules if m.split('.')[0] in ('server', 'arslan')))")
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=60,
                         env={**os.environ, "PYTHONPATH": str(root)})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "['server', 'server.run_kinds']"
