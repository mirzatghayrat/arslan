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

import pytest

from scripts import usage_report
from scripts.kernel_bench import report as bench_report
from server.orchestrator import run_trace
from server.services import command_sandbox, run_recorder, terminal_exec
from tests.test_usage_report import SCHEMA
from tests.server.test_s64_0_outside_content_gaps import memory  # noqa: F401 — the fixture

DENIED = "x: Operation not permitted\n"


# ── 1. the denial code, from the command to the weekly report ────────────────

@pytest.mark.parametrize("stderr, code", [(DENIED, "eperm"), ("x: no such file\n", None)])
async def test_a_command_the_sandbox_stopped_notes_its_code_off_the_result(tmp_path, monkeypatch, stderr, code):
    """The code goes to the call's trace entry, never onto the result the model and every payload read."""
    monkeypatch.setattr(command_sandbox, "wrapper", lambda *a, **kw: ["/usr/bin/env"])     # runs it as "workspace"
    with run_trace.collecting() as trace:
        result = await terminal_exec.run(f"printf '{stderr}' >&2; exit 1", cwd=tmp_path, sandbox=True)
        run_trace.record(tool="run_command", args={}, result=result, ok=False, error="exit code 1", ms=5)
    assert result["sandbox"] == "workspace" and bool(result.get("sandbox_denied")) is (code is not None)
    assert "denial" not in json.dumps(result) and "eperm" not in json.dumps(result)
    assert trace[0].get("denial") == code


def test_the_code_reaches_the_run_step_of_its_own_tool_however_long_the_output():
    with run_trace.collecting():
        run_trace.note_denial("eperm")
        run_trace.record(tool="run_command", args={"command": "x"}, ok=False, error="exit code 1", ms=5,
                         result={"ok": False, "stdout": "y" * 5000, "sandbox_denied": True})
        run_trace.note_denial("eperm")                      # a credential refusal's entry has no step of its own
        run_trace.record(tool="run_command", args={"command": "z"}, ok=False, error="refused", ms=1, result={})
        run_trace.note_denial("not-a-code")                 # only a known code is kept
        run_trace.record(tool="run_command", args={"command": "w"}, ok=True, error=None, ms=5, result={"ok": True})
        run_trace.note_denial("eperm")                      # only a command's entry takes one
        run_trace.record(tool="web_search", args={}, ok=True, error=None, ms=5, result={"ok": True})
        trace = run_trace.snapshot()
        steps = [{"kind": "tool_call", "ref": {"tool": tool}, "detail": {}}
                 for tool in ("run_command", "web_search", "run_command")]
        run_recorder.RunRecorder._merge_tool_trace(None, steps)
    assert steps[0]["ref"] == {"tool": "run_command", "ok": False, "denial": "eperm"}
    assert steps[1]["ref"] == {"tool": "web_search", "ok": False}       # paired by order, another tool: no code
    assert steps[2]["ref"] == {"tool": "run_command", "ok": True}
    assert "denial" not in trace[3]


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
             ({"tool": "web_search", "ok": True}, "SECRET-RESULT"),
             ({"tool": "web_search", "ok": False, "denial": "eperm"}, "SECRET-RESULT")]   # not a command: not counted
    con.executemany("INSERT INTO run_steps (run_id, kind, ref, detail, duration_ms) VALUES (1, 'tool_call', ?, ?, 5)",
                    [(json.dumps(ref), json.dumps({"result_raw": raw})) for ref, raw in steps])
    cards = [("retry", "user"), ("retry", "user"), ("retry", "expired"), ("outside", "user"), (None, "user"),
             ("retry", "policy")]                     # nobody to ask: never a card on screen, not counted
    con.executemany("INSERT INTO approval_events (created_at, kind, target, detail, decided_by, decision, extra) "
                    "VALUES (?, 'outside', '*', 'SECRET-COMMAND', ?, 'deny', ?)",
                    [(week, by, json.dumps({"sandbox": card}) if card else None) for card, by in cards])
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


@pytest.mark.parametrize("rerun", [True, False], ids=["re-run outside", "nobody to ask"])
async def test_a_denial_reaches_the_local_record_and_no_outgoing_payload(memory, monkeypatch, rerun):  # noqa: F811
    """Card §"The two numbers": the code is shown only by the weekly report and the local run detail, and is
    absent from every outgoing payload. A whole host turn runs a command the sandbox stops, and the user lets it
    re-run outside, or nobody can be asked (a scheduled run), which puts the re-run card in the Inbox's refused
    list. Then each payload that leaves the process today is read: the model's next
    request, the phone's run detail and live steps, the judge's evidence and the Inbox's refused list. The
    model still sees the command's own words, and the step's `ref` keeps the code either way."""
    from datetime import datetime
    from sqlalchemy import select
    from server.db import session as db_session
    from server.db.models import Run, RunStep
    from server.orchestrator import tool_loop
    from server.orchestrator.tool_caller import ToolCaller
    from server.services import command_confirm, host_run, permission_store, permissions, phone_reads
    from server.services import task_service
    from server.services import personal_context as pc, trace_evidence
    from tests.server.test_s64_0_outside_content_gaps import CID, _Asker, _Cards, _ctx, _Model, _turn

    monkeypatch.setattr(command_sandbox, "wrapper", lambda *a, **kw: ["/usr/bin/env"])     # runs it as "workspace"
    model = _Model(**{"S64-HOST": _turn(("run_command", {"command": f"printf '{DENIED}' >&2; exit 1"}))})
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    events = []

    async def tools():
        return [{"key": "run_command", "description": "Run a command"}]

    async def function(cid, message, emit):
        async def body(capture):                                # host_run records the Run and its steps
            def both(event):
                events.append(event)
                capture(event)
            result = await tool_loop.run_native(
                system="S64-HOST", user_content=message, history=[], emit=both, on_chunk=lambda c: None,
                resolve_tools=tools, conversation_id=cid,
                confirm_command=_Cards() if rerun else command_confirm.Confirmations(cid).command,
                caller=ToolCaller(actor="host", spawn_id=None, conversation_id=cid))
            return result["final"]
        return await host_run.execute(cid, message, emit, body)
    with pc.bind(_ctx()), permissions.asking_with(_Asker() if rerun else None):
        await task_service.run_turn(function, CID, "run it", lambda e: None)

    seen = json.dumps(model.requests["S64-HOST"][1], ensure_ascii=False)
    assert "Operation not permitted" in seen                    # the command's own words
    async with db_session.AsyncSessionLocal() as db:
        run = (await db.execute(select(Run).order_by(Run.id.desc()))).scalars().first()
        step = (await db.execute(select(RunStep).where(RunStep.run_id == run.id,
                                                        RunStep.kind == "tool_call"))).scalars().one()
        outgoing = {"model": seen, "phone run": await phone_reads.run_detail(db, run.id),
                    "refused": await permission_store.refused_groups(db, datetime(2000, 1, 1))}
    outgoing["phone live"] = phone_reads.live_steps([(None, event) for event in events])
    outgoing["judge"] = await trace_evidence.build_evidence(run.id)
    assert step.ref.get("denial") == "eperm"                    # kept locally, whatever the user answered
    assert rerun or outgoing["refused"], "the re-run card nobody could answer is in the Inbox's refused list"
    for name, payload in outgoing.items():
        text = json.dumps(payload, ensure_ascii=False, default=str)
        assert "eperm" not in text and "denial" not in text, name


# ── the bench ────────────────────────────────────────────────────────────────

def test_the_bench_reports_the_cards_re_run_share():
    """The card's number 2: re-run cards ÷ run_command calls that ran in the sandbox. Every card is declined in
    a round, so a call asked up front never ran."""
    records = [{"entrant": "arslan", "model": "m", "sandbox_cards": {"retry": 2, "outside": 1, "run_commands": 9}},
               {"entrant": "arslan", "model": "m", "sandbox_cards": {"retry": 0, "outside": 0, "run_commands": 1}},
               {"entrant": "codex", "model": "m", "sandbox_cards": {"retry": None, "outside": None}}]
    counts = bench_report.sandbox_cards(records)
    assert counts == {("arslan", "m"): {"runs": 2, "retry": 2, "outside": 1, "run_commands": 10}}
    assert bench_report.rerun_share(counts[("arslan", "m")]) == 2 / 9
    assert "| arslan | m | 2 | 10 | 2 | 22% | 1 |" in bench_report.render_sandbox_cards(records)
    assert bench_report.rerun_share({"retry": 0, "outside": 1, "run_commands": 1}) is None
