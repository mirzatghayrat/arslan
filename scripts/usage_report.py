"""Weekly usage numbers from the local Arslan database: read-only, numbers only (0.1.62 M2).

    python -m scripts.usage_report [--db PATH] [--weeks N] [--since YYYY-MM-DD]

One row per week (Monday to Sunday, local time) for each line of the §5.2 table in
docs/plans/2026-10-17-0162-execution-first.md. Without --db the database is found the way
the server finds it: ARSLAN_DB_PATH, else <data dir>/arslan.db. It is opened read-only:
SQLite refuses every write and never checkpoints, the database and its WAL are not touched,
and no side file is left behind (see connect_ro). The app may be running.

Only counts and fixed product codes come back from SQLite. Text is matched inside SQL;
every MCP tool (key `mcp_<server id>__<name>`, server/mcp/discovery.py:56-64) is folded
into one `mcp` row; any other tool name prints only when the product registered it
(BUILT_IN_TOOLS or the `tools` table), since a refused call keeps whatever name the model
made up; any other code that is not a short lowercase code prints as `other`.
Conversation text, commands, paths, app names, error text and tool arguments never reach
Python.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from server.run_kinds import USER_RUN_KINDS   # imports nothing: the report never loads the server

WEEK = timedelta(days=7)
# Before F1 (v0.1.62) the loop cut run_command at 20 s with this text. Since F1 a run_command over its
# limit reports OUTER_LIMIT (tool_loop.py:1856), and no tool produces this text any more.
CUT_TEXT = "tool 'run_command' timed out"
OWN_LIMIT = "stopped after %"                 # terminal_exec.py:149: the command's own limit
OUTER_LIMIT = "stopped by the time limit; no output was captured%"   # F1's outer limit, tool_loop.py:1856
CUT_MS = (19_500, 21_500)                     # a failed run_command that ran about 20 s
SHOWN = "('user', 'expired')"                 # approval_events.decided_by: the card opened
# Tool names the product defines but never stores in `tools`: every key of
# server/registry/executors.py EXECUTORS (a test keeps this in step) and the host's own
# bookkeeping tools (server/orchestrator/arslan.py). `tools` adds the seeded catalog and MCP.
BUILT_IN_TOOLS = frozenset("""
    attach_file background_status browser_back browser_click browser_look browser_open browser_press
    browser_select browser_type cancel_task conversation_search create_skill delegate_work
    desktop_access desktop_apps desktop_batch desktop_click desktop_look desktop_menu
    desktop_open desktop_press desktop_scroll desktop_select desktop_takeover desktop_type
    edit_file enroll_node find_capability list_dir list_my_capabilities list_my_tasks list_nodes
    mac_applescript mac_list_shortcuts mac_run_shortcut memory_note read_file read_skill recall
    remember render_chart render_deck run_command run_python scan_local_network schedule_task
    search_files ssh_probe ssh_run start_background_work stop_background_work task_progress
    web_extract web_search whats_new write_file
    ask_user_choice propose_capability propose_plan_change update_plan
""".split())


def _lit(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _json(col: str, key: str) -> str:
    """json_extract of one named key; NULL (not an error) when the column is not JSON."""
    return f"CASE WHEN json_valid({col}) THEN json_extract({col}, '$.{key}') END"


def _code(expr: str) -> str:
    """SQL: `expr` when it is a short lowercase code, 'none' when empty, else 'other'."""
    return (f"CASE WHEN COALESCE({expr}, '') = '' THEN 'none' WHEN length({expr}) <= 40 "
            f"AND {expr} GLOB '[a-z]*' AND {expr} NOT GLOB '*[^a-z0-9_.:-]*' THEN {expr} "
            "ELSE 'other' END")


def _n(cond: str) -> str:
    return f"COALESCE(SUM({cond}), 0)"


def _week(col: str) -> str:
    return f"datetime({col}) >= ? AND datetime({col}) < ?"


def _users_runs(col: str) -> str:
    """The user's own runs (server/run_kinds.py), as the usage page counts them: chat turns, fires,
    background jobs and browser previews ('host'; older rows 'live' and 'scheduled'); never replay or
    helper runs."""
    return f"{col} IN ({', '.join(map(_lit, USER_RUN_KINDS))})"


TOOL, ERROR = _json("s.ref", "tool"), _json("s.detail", "error")   # run_recorder.py:241, :485-487
FAILED = _json("s.ref", "ok") + " = 0"
IS_MCP = f"substr({TOOL}, 1, 4) = 'mcp_'"
REGISTERED = (f"({TOOL} IN ({', '.join(map(_lit, sorted(BUILT_IN_TOOLS)))}) "
              f"OR {TOOL} IN (SELECT key FROM tools))")
STEPS = ("FROM run_steps s JOIN runs r ON r.id = s.run_id "
         f"WHERE s.kind = 'tool_call' AND {_users_runs('r.kind')} AND {_week('r.started_at')}")
CUT, OWN = f"{ERROR} = {_lit(CUT_TEXT)}", f"{ERROR} LIKE {_lit(OWN_LIMIT)}"
OUTER, NEAR_20S = f"{ERROR} LIKE {_lit(OUTER_LIMIT)}", "s.duration_ms BETWEEN %d AND %d" % CUT_MS
# A provider refusing a tool's parameter schema (the 2026-10-14 MCP incident): Anthropic says
# `tools.<n>.custom.input_schema: ...`, OpenAI-compatible ones `Invalid schema for function`.
# A run recorded the failure as ModelCallError before host runs; a host run (every chat turn since
# 2026-09-14) records HostError with the error frame's text (host_run.py:71), which for a provider error
# the frame does not translate is ModelCallError's own message (llm_errors.error_frame, model_call.py:88).
MODEL_CALL_FAILED = ("(error_kind = 'ModelCallError' OR (error_kind = 'HostError' "
                     "AND instr(error_text, 'Model request failed (') = 1))")
SCHEMA_400 = (MODEL_CALL_FAILED + " AND instr(error_text, 'HTTP 400') > 0 AND ("
              "instr(error_text, 'input_schema') > 0"
              " OR instr(lower(error_text), 'invalid schema') > 0"
              " OR instr(error_text, 'is not a regex') > 0 OR error_text GLOB '*tools.[0-9]*'"
              " OR error_text GLOB '*mcp_[0-9]*__*')")
WAITING = "phase = 'waiting_user'"
# turn_facts.py:105 (facts) and orchestrator/memory.py:165 (summary), after the answer
FACTS, SUMMARY = "scope = 'memory_facts'", "scope = 'memory'"

# (sql, names): one row of counts per week. Every `?` pair is the week's (start, end).
WEEKLY = [
    (f"SELECT COUNT(*), {_n(SCHEMA_400)} FROM runs WHERE {_users_runs('kind')} "
     f"AND {_week('started_at')}", ("runs", "mcp_turns_by_text")),
    (f"SELECT COUNT(*), {_n(WAITING)} FROM companion_tasks WHERE {_week('created_at')}",
     ("tasks", "waiting")),
    (f"SELECT COUNT(*), {_n(FAILED)}, {_n(IS_MCP)}, {_n(IS_MCP + ' AND ' + FAILED)} {STEPS}",
     ("calls", "failed", "mcp_calls", "mcp_failed")),
    (f"SELECT COUNT(*), {_n(CUT)}, {_n(OWN)}, {_n(OUTER)}, {_n(NEAR_20S)} {STEPS} "
     f"AND {TOOL} = 'run_command' AND {FAILED}",
     ("rc_failed", "rc_cut", "rc_own_limit", "rc_outer_limit", "rc_cut_by_ms")),
    (f"SELECT COUNT(*) FROM conversation_events WHERE kind = 'mcp_schema_relaxed' "
     f"AND {_week('created_at')}", ("mcp_relaxed",)),
    (f"SELECT {_n('decided_by IN ' + SHOWN)}, {_n('decided_by NOT IN ' + SHOWN)} "
     f"FROM approval_events WHERE {_week('created_at')}", ("cards_shown", "cards_auto")),
    (f"SELECT {_n(FACTS)}, {_n(SUMMARY)} FROM usage_ledger WHERE {_week('ts')}",
     ("memory_facts", "memory")),
]
# name -> GROUP BY query: (code, count) or, for tools, (code, calls, failed).
BREAKDOWNS = {
    "waiting_reasons": f"SELECT {_code('pause_reason')}, COUNT(*) FROM companion_tasks "
                       f"WHERE {WAITING} AND {_week('created_at')} GROUP BY 1",
    "tools": f"SELECT CASE WHEN {IS_MCP} THEN 'mcp' WHEN {REGISTERED} THEN {TOOL} "
             f"ELSE 'other' END, COUNT(*), {_n(FAILED)} {STEPS} GROUP BY 1",
    "shown_by_kind": f"SELECT {_code('kind')}, COUNT(*) FROM approval_events "
                     f"WHERE decided_by IN {SHOWN} AND {_week('created_at')} GROUP BY 1",
}


def default_db() -> Path:
    """server/config.py's rule (load_settings): ARSLAN_DB_PATH, else <data dir>/arslan.db.
    profile_paths only computes the path; importing or calling it creates nothing."""
    from server.profile_paths import resolve_database
    return resolve_database()


def connect_ro(path) -> sqlite3.Connection:
    """Read-only, leaving the folder as it was found.

    The app keeps the database in WAL mode (server/db/session.py:29), and SQLite deletes its
    -wal and -shm files when the last connection closes. A plain mode=ro reader of a WAL
    database creates both when they are missing, and leaves them behind. So with no -wal,
    -shm or -journal (nobody has it open) it is opened immutable=1: no locks, no side files.
    Otherwise the app is running and mode=ro reads through the app's own -shm index (taking
    a read slot there, as any reader does) without writing the database or its WAL. Either
    way SQLite refuses every write and never checkpoints."""
    path = Path(path).resolve()
    in_use = any(Path(f"{path}{side}").exists() for side in ("-wal", "-shm", "-journal"))
    return sqlite3.connect(f"{path.as_uri()}?mode=ro{'' if in_use else '&immutable=1'}", uri=True)


def week_starts(today: date, weeks: int | None, since: date | None) -> list[date]:
    """Mondays of the weeks to report: `weeks` (default 4) up to this one, or from `since`'s
    week on (through this week unless `weeks` is given)."""
    this_monday = today - timedelta(days=today.weekday())
    if since is None:
        first = this_monday - WEEK * ((weeks or 4) - 1)
    else:
        first = since - timedelta(days=since.weekday())
    count = weeks or max(1, (this_monday - first).days // 7 + 1)
    return [first + WEEK * i for i in range(count)]


def _utc(day: date) -> str:
    """Local midnight starting `day`, as the naive UTC text the app stores (utcnow)."""
    local = datetime.combine(day, time())
    return local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _run(con: sqlite3.Connection, sql: str, bound: tuple[str, str]):
    return con.execute(sql, bound * (sql.count("?") // 2))


def _split(con: sqlite3.Connection, sql: str, bounds: list) -> dict:
    """{code: [value per week]} for a GROUP BY query; a value is a count or (calls, failed)."""
    out: dict = {}
    for i, bound in enumerate(bounds):
        for code, *counts in _run(con, sql, bound):
            value = counts[0] if len(counts) == 1 else tuple(counts)
            zero = 0 if len(counts) == 1 else (0,) * len(counts)
            out.setdefault(code, [zero] * len(bounds))[i] = value
    return out


def collect(con: sqlite3.Connection, weeks: list[date]) -> dict:
    bounds = [(_utc(w), _utc(w + WEEK)) for w in weeks]
    weekly = []
    for bound in bounds:
        row: dict = {}
        for sql, names in WEEKLY:
            row.update(zip(names, _run(con, sql, bound).fetchone()))
        weekly.append(row)
    found = {name: _split(con, sql, bounds) for name, sql in BREAKDOWNS.items()}
    return {"weekly": weekly, **found}


def _table(head: list, rows: list) -> list[str]:
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    return lines + ["| " + " | ".join(str(cell) for cell in r) + " |" for r in rows]


def _pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "–"


def _ordered(found: dict) -> list:
    """Most failures (or most rows) first, then by code."""
    def weight(item):
        return (-sum(c[-1] if isinstance(c, tuple) else c for c in item[1]), item[0])
    return sorted(found.items(), key=weight)


def render(weeks: list[date], data: dict) -> str:
    labels = [f"{w:%Y-%m-%d} – {w + timedelta(days=6):%Y-%m-%d}" for w in weeks]
    offset = datetime.now().astimezone().strftime("%z")
    out = ["# Arslan weekly usage", "",
           f"Weeks run Monday to Sunday, local time (UTC{offset[:3]}:{offset[3:]}). Read-only; "
           "numbers and fixed codes only. ≈ = inferred, see the note under the table.", ""]

    def weekly(title, head, cells, note):
        rows = [[label, *cells(w)] for label, w in zip(labels, data["weekly"])]
        out.extend([title, "", *_table(["Week", *head], rows), "", note, ""])

    def split(title, rows):
        rows = rows or [["(none)", *["0"] * len(labels)]]
        out.extend([title, "", *_table(["Code", *labels], rows), ""])

    def plain(found, prefix=""):
        return [[prefix + code, *cells] for code, cells in _ordered(found)]

    weekly("## Runs and tasks", ["Runs", "Tasks", "Waiting on you", "Share"],
           lambda w: [w["runs"], w["tasks"], w["waiting"], _pct(w["waiting"], w["tasks"])],
           "Chat turns, scheduled fires, background jobs and browser previews by start (run kinds " +
           ", ".join(USER_RUN_KINDS) + "; never replay or helper runs). Tasks by the week they were "
           "created, counted by the phase they are in now.")
    split("### Waiting on you, by reason", plain(data["waiting_reasons"]))
    weekly("## Tool calls", ["Calls", "Failed", "Failure rate", "MCP calls", "MCP failed"],
           lambda w: [w["calls"], w["failed"], _pct(w["failed"], w["calls"]), w["mcp_calls"],
                      w["mcp_failed"]],
           "Tool steps of those runs, by the run's start. Every mcp_<server>__<name> tool is "
           "one `mcp` row; a name the product never registered is `other`.")
    split("### Tool calls by tool (failed/calls)",
          [[code, *(f"{c[1]}/{c[0]}" for c in cells)] for code, cells in _ordered(data["tools"])])
    weekly("## run_command time limits",
           ["Failed", "20 s cut", "Own limit", "Outer limit (F1)", "Ran 19.5–21.5 s"],
           lambda w: [w["rc_failed"], w["rc_cut"], w["rc_own_limit"], w["rc_outer_limit"],
                      f"≈{w['rc_cut_by_ms']}"],
           "Columns 2-4 match the product's own fixed error text: `tool 'run_command' timed "
           "out` (the 20 s cut before F1, v0.1.62; 0 in later weeks), `stopped after N s` and "
           "F1's `stopped by the time limit`. ≈ by duration: failed run_command steps that ran "
           "19.5–21.5 s, evidence for the old cut.")
    weekly("## MCP whole-turn failures", ["HTTP 400 tool schema", "mcp_schema_relaxed events"],
           lambda w: [f"≈{w['mcp_turns_by_text']}", w["mcp_relaxed"]],
           "≈ by text: turns that failed on a model call (ModelCallError, or a host run's "
           "HostError carrying its message) with HTTP 400 and a tool-schema refusal "
           "(input_schema, invalid schema, not a regex, tools.<n>, mcp_<id>__). "
           "mcp_schema_relaxed events start with F3.")
    weekly("## Cards", ["Ledger: cards shown", "Ledger: auto-decided"],
           lambda w: [w["cards_shown"], w["cards_auto"]],
           "Shown = decided by user or expired; auto = any other decider. Sandbox-exit cards "
           "reach the ledger only after S4a. (The judgments table's command-card rows went with "
           "the shadow judge in C4; old ones age out under KEEP_DAYS.)")
    split("### Cards shown, by kind (ledger)", plain(data["shown_by_kind"]))
    weekly("## Post-turn model calls", ["memory_facts rows", "memory rows"],
           lambda w: [w["memory_facts"], w["memory"]],
           "usage_ledger rows: one per scope and model, so about one per call (a scope that "
           "switched model writes one more).")
    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Weekly usage numbers from the local Arslan "
                                             "database (read-only, numbers only).")
    ap.add_argument("--db", help="database (default: ARSLAN_DB_PATH, else <data dir>/arslan.db)")
    ap.add_argument("--weeks", type=int,
                    help="number of weeks (default 4; with --since, through the current week)")
    ap.add_argument("--since", type=date.fromisoformat,
                    help="start with the week holding this date (YYYY-MM-DD)")
    args = ap.parse_args(argv)
    if args.weeks is not None and args.weeks < 1:
        ap.error("--weeks must be at least 1")
    path = Path(args.db).expanduser() if args.db else default_db()
    if not path.is_file():
        print("No Arslan database there; pass --db PATH.", file=sys.stderr)
        return 2
    weeks = week_starts(date.today(), args.weeks, args.since)
    with closing(connect_ro(path)) as con:
        print(render(weeks, collect(con, weeks)), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
