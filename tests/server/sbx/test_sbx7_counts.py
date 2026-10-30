"""SBX-7 (v0.1.64): the two numbers SBX is measured by, from now on (docs/plans/0164/SBX-sandbox.md, Goal 5).

1. The local count of sandbox denials, never uploaded:
   - a command the sandbox stopped carries a denial code (`sandbox_denial`, EPERM so far, SBX-3);
   - the run step keeps it on its `ref`, which `result_raw`'s 2,000-character cut never reaches;
   - the weekly report counts it.
2. Re-run cards against ask-up-front cards:
   - the ledger row says which one a card was (`extra.sandbox`), with no change to `permissions.py`;
   - the weekly report counts both;
   - the bench counts them apart and reports re-run cards per run.
"""
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from scripts import usage_report
from scripts.kernel_bench import report as bench_report
from server.orchestrator import run_trace
from server.services import command_sandbox, run_recorder, terminal_exec
from tests.test_usage_report import SCHEMA

DENIED = "x: Operation not permitted\n"


# ── 1. the denial code, from the command to the weekly report ────────────────

@pytest.mark.parametrize("stderr, code", [(DENIED, "eperm"), ("x: no such file\n", None)])
async def test_a_command_the_sandbox_stopped_carries_its_denial_code(tmp_path, monkeypatch, stderr, code):
    monkeypatch.setattr(command_sandbox, "wrapper", lambda *a, **kw: ["/usr/bin/env"])     # runs it as "workspace"
    result = await terminal_exec.run(f"printf '{stderr}' >&2; exit 1", cwd=tmp_path, sandbox=True)
    assert result["sandbox"] == "workspace" and result.get("sandbox_denial") == code
    assert bool(result.get("sandbox_denied")) is (code is not None)


def test_the_code_reaches_the_run_step_however_long_the_output():
    with run_trace.collecting():
        run_trace.record(tool="run_command", args={"command": "x"}, ok=False, error="exit code 1", ms=5,
                         result={"ok": False, "stdout": "y" * 5000, "sandbox_denied": True, "sandbox_denial": "eperm"})
        run_trace.record(tool="run_command", args={"command": "z"}, ok=True, error=None, ms=5,
                         result={"ok": True, "stdout": "fine"})
        steps = [{"kind": "tool_call", "ref": {"tool": "run_command"}, "detail": {}} for _ in range(2)]
        run_recorder.RunRecorder._merge_tool_trace(None, steps)
    assert '"sandbox_denial"' not in steps[0]["detail"]["result_raw"]     # cut away with the long output
    assert steps[0]["ref"] == {"tool": "run_command", "ok": False, "denial": "eperm"}
    assert steps[1]["ref"] == {"tool": "run_command", "ok": True}


# ── 2. which card it was, in the ledger ──────────────────────────────────────

@pytest.mark.parametrize("sandbox", ["outside", "retry"])
async def test_the_ledger_row_says_which_sandbox_card_it_was(monkeypatch, sandbox):
    from server.services import command_confirm, permissions
    seen = []

    async def decide(req, ctx):
        seen.append(req)
        return permissions.Decision(False, "user")
    monkeypatch.setattr(permissions, "decide", decide)
    assert await command_confirm.Confirmations("c1").command("mv a ~/b", [], sandbox=sandbox) is False
    assert seen[0].kind == "outside" and seen[0].extra == {"sandbox": sandbox}


# ── the weekly report ────────────────────────────────────────────────────────

@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "arslan.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    week = "2026-10-06 10:00:00"
    con.execute("INSERT INTO runs (id, kind, started_at) VALUES (1, 'host', ?)", (week,))       # a chat turn
    steps = [({"tool": "run_command", "ok": False, "denial": "eperm"}, "SECRET-RESULT"),
             ({"tool": "run_command", "ok": False, "denial": "eperm"}, "SECRET-RESULT"),
             ({"tool": "run_command", "ok": False}, "SECRET-RESULT"),
             ({"tool": "web_search", "ok": True}, "SECRET-RESULT")]
    con.executemany("INSERT INTO run_steps (run_id, kind, ref, detail, duration_ms) VALUES (1, 'tool_call', ?, ?, 5)",
                    [(json.dumps(ref), json.dumps({"result_raw": raw})) for ref, raw in steps])
    cards = [{"sandbox": "retry"}, {"sandbox": "retry"}, {"sandbox": "retry"}, {"sandbox": "outside"}, None]
    con.executemany("INSERT INTO approval_events (created_at, kind, target, detail, decided_by, decision, extra) "
                    "VALUES (?, 'outside', '*', 'SECRET-COMMAND', 'user', 'deny', ?)",
                    [(week, json.dumps(extra) if extra else None) for extra in cards])
    con.commit()
    con.close()
    return path


def test_the_weekly_report_counts_denials_and_both_cards(ledger, capsys):
    con = usage_report.connect_ro(ledger)
    try:
        data = usage_report.collect(con, [date(2026, 10, 5)])
    finally:
        con.close()
    week = data["weekly"][0]
    assert (week["rc_sandbox_denied"], week["retry_cards"], week["outside_cards"]) == (2, 3, 1)
    assert usage_report.main(["--db", str(ledger), "--since", "2026-10-05", "--weeks", "1"]) == 0
    out = capsys.readouterr().out
    assert "## Sandbox" in out and "SECRET" not in out


def test_the_denial_count_goes_nowhere_but_the_local_report():
    """Goal 5: the count is local. Its key is written by the run recorder and read only by the weekly report."""
    root = Path(__file__).resolve().parents[3]
    readers = sorted(str(p.relative_to(root)) for folder in ("server", "scripts", "arslan")
                     for p in (root / folder).rglob("*.py") if '"denial"' in p.read_text(encoding="utf-8"))
    assert readers == ["scripts/usage_report.py", "server/orchestrator/run_trace.py", "server/services/run_recorder.py"]


# ── the bench ────────────────────────────────────────────────────────────────

def test_the_bench_reports_re_run_cards_per_run():
    records = [{"entrant": "arslan", "model": "m", "sandbox_cards": {"retry": 2, "outside": 1}},
               {"entrant": "arslan", "model": "m", "sandbox_cards": {"retry": 0, "outside": 0}},
               {"entrant": "codex", "model": "m", "sandbox_cards": {"retry": None, "outside": None}}]
    assert bench_report.sandbox_cards(records) == {("arslan", "m"): {"runs": 2, "retry": 2, "outside": 1}}
    assert "| arslan | m | 2 | 2 | 1.00 | 1 |" in bench_report.render_sandbox_cards(records)
