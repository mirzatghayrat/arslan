"""SBX-7 (v0.1.64): the two numbers SBX is measured by, from now on (docs/plans/0164/SBX-sandbox.md, Goal 5).

1. The local count of sandbox denials, never uploaded:
   - a command the sandbox stopped notes a denial code (EPERM so far, SBX-3), never on its result;
   - the run step keeps it on its `ref`, which `result_raw`'s 2,000-character cut never reaches;
   - the weekly report counts it.
2. Cards to leave the sandbox (the calibration of 2026-11-07: a denial goes back to the model, and leaving is its
   deliberate request, so what counts is how many there are):
   - the weekly report counts them from the ledger (`kind = 'outside'`, cards that opened);
   - the bench reports them per entrant and per task, against `run_command` calls and every card.
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
    # A stop shows no card, so the failed step says what stopped it. Any other failure is its exit code, as before.
    assert result["error"] == ("the sandbox stopped this command (exit code 1)" if code else "exit code 1")


async def test_a_time_limit_keeps_its_exact_text_when_the_output_reads_like_a_stop(tmp_path, monkeypatch):
    """M2 counts "stopped after N s": a command that printed the words and then ran out of time is still a time limit."""
    monkeypatch.setattr(command_sandbox, "wrapper", lambda *a, **kw: ["/usr/bin/env"])     # runs it as "workspace"
    result = await terminal_exec.run(f"printf '{DENIED}' >&2; sleep 30", cwd=tmp_path, sandbox=True, timeout_s=1)
    assert result["sandbox_denied"] is True and result["code"] == "time_limit"
    assert result["error"] == "stopped after 1 s"


def test_the_code_reaches_the_run_step_of_its_own_tool_however_long_the_output():
    with run_trace.collecting():
        run_trace.note_denial("eperm")
        run_trace.record(tool="run_command", args={"command": "x"}, ok=False, error="exit code 1", ms=5,
                         result={"ok": False, "stdout": "y" * 5000, "sandbox_denied": True})
        run_trace.note_denial("eperm")                      # a credential refusal's entry has no step of its own
        run_trace.record(tool="run_command", args={"command": "z"}, ok=False, error="refused", ms=1, result={})
        run_trace.record(tool="run_command", args={"command": "w"}, ok=True, error=None, ms=5, result={"ok": True})
        steps = [{"kind": "tool_call", "ref": {"tool": tool}, "detail": {}}
                 for tool in ("run_command", "web_search", "run_command")]
        run_recorder.RunRecorder._merge_tool_trace(None, steps)
    assert steps[0]["ref"] == {"tool": "run_command", "ok": False, "denial": "eperm"}
    assert steps[1]["ref"] == {"tool": "web_search", "ok": False}       # paired by order, another tool: no code
    assert steps[2]["ref"] == {"tool": "run_command", "ok": True}


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
    cards = [("outside", "user"), ("outside", "user"), ("outside", "expired"),
             ("outside", "policy"),                   # nobody to ask: never a card on screen, not counted
             ("command", "user")]                     # an ordinary card, inside the sandbox
    con.executemany("INSERT INTO approval_events (created_at, kind, target, detail, decided_by, decision) "
                    "VALUES (?, ?, '*', 'SECRET-COMMAND', ?, 'deny')", [(week, *card) for card in cards])
    con.commit()
    con.close()
    return path


def test_the_weekly_report_counts_denials_and_cards_to_leave_the_sandbox(ledger, capsys):
    con = usage_report.connect_ro(ledger)
    try:
        data = usage_report.collect(con, [date(2026, 10, 5)])
    finally:
        con.close()
    week = data["weekly"][0]
    assert (week["rc_sandbox_denied"], week["leave_cards"]) == (2, 3)
    assert usage_report.main(["--db", str(ledger), "--since", "2026-10-05", "--weeks", "1"]) == 0
    out = capsys.readouterr().out
    assert "## Sandbox" in out and "SECRET" not in out


@pytest.mark.parametrize("someone_to_ask", [True, False], ids=["someone to ask", "nobody to ask"])
async def test_a_denial_reaches_the_local_record_and_no_outgoing_payload(memory, monkeypatch, someone_to_ask):  # noqa: F811
    """Card §"The two numbers": the code is shown only by the weekly report and the local run detail, and is
    absent from every outgoing payload. A whole host turn runs a command the sandbox stops, with someone to ask or
    with nobody (a scheduled run). A stop goes back to the model and opens no card either way, so nothing joins the
    Inbox's refused list. Then each payload that leaves the process today is read: the model's next
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

    class _RecordedCards(_Cards):
        calls: list = []

        async def __call__(self, command, argv, **kw):
            self.calls.append(kw)
            return await super().__call__(command, argv, **kw)

    monkeypatch.setattr(command_sandbox, "wrapper", lambda *a, **kw: ["/usr/bin/env"])     # runs it as "workspace"
    model = _Model(**{"S64-HOST": _turn(("run_command", {"command": f"printf '{DENIED}' >&2; exit 1"}))})
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    events = []
    cards, asker = _RecordedCards(), _Asker()

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
                confirm_command=cards if someone_to_ask else command_confirm.Confirmations(cid).command,
                caller=ToolCaller(actor="host", spawn_id=None, conversation_id=cid))
            return result["final"]
        return await host_run.execute(cid, message, emit, body)
    with pc.bind(_ctx()), permissions.asking_with(asker if someone_to_ask else None):
        await task_service.run_turn(function, CID, "run it", lambda e: None)

    seen = json.dumps(model.requests["S64-HOST"][1], ensure_ascii=False)
    assert "Operation not permitted" in seen, seen[:1500]       # the command's own words
    async with db_session.AsyncSessionLocal() as db:
        run = (await db.execute(select(Run).order_by(Run.id.desc()))).scalars().first()
        step = (await db.execute(select(RunStep).where(RunStep.run_id == run.id,
                                                        RunStep.kind == "tool_call"))).scalars().one()
        outgoing = {"model": seen, "phone run": await phone_reads.run_detail(db, run.id),
                    "refused": await permission_store.refused_groups(db, datetime(2000, 1, 1))}
    outgoing["phone live"] = phone_reads.live_steps([(None, event) for event in events])
    outgoing["judge"] = await trace_evidence.build_evidence(run.id)
    assert step.ref.get("denial") == "eperm"                    # kept locally, whatever the user answered
    assert cards.calls == [] and asker.frames == [] and outgoing["refused"] == []    # a stop shows no card, to anyone
    for name, payload in outgoing.items():
        text = json.dumps(payload, ensure_ascii=False, default=str)
        assert "eperm" not in text and "denial" not in text, name


# ── the bench ────────────────────────────────────────────────────────────────

def _record(task, policy, leave, asked, calls, entrant="arslan"):
    return {"entrant": entrant, "model": "m", "task": task, "shell_policy": policy,
            "sandbox_cards": {"leave": leave, "asked": asked, "run_commands": calls}}


RECORDS = [_record("T1", "ask_risky", 2, 5, 8), _record("T1", "ask_risky", 0, 1, 2), _record("T2", "ask_all", 1, 4, 4),
           _record("T3", "ask_risky", 0, 0, 0),
           _record("T4", "ask_risky", None, 3, 3),              # the bench's own sandbox: Arslan's wasn't on, so no count
           _record("T1", None, None, None, None, entrant="codex")]


def test_the_bench_reports_cards_to_leave_the_sandbox_per_entrant():
    """The card's number 2: of the `run_command` calls, how many asked to leave the sandbox."""
    counts = bench_report.sandbox_cards(RECORDS)
    assert counts == {("arslan", "m"): {"runs": 4, "leave": 3, "asked": 10, "run_commands": 14}}
    assert bench_report.leave_share(counts[("arslan", "m")]) == 3 / 14
    assert "| arslan | m | 4 | 14 | 10 | 3 | 21% |" in bench_report.render_sandbox_cards(RECORDS)


def test_the_bench_reports_them_per_task_and_policy():
    """SBX-8 runs the same tasks under "ask for every command" and "ask only when risky": cards per task is its number,
    and the classifier's baseline."""
    text = bench_report.render_cards_per_task(RECORDS)
    assert "| arslan | m | ask_risky | T1 | 2 | 10 | 6 | 2 | 20% |" in text
    assert "| arslan | m | ask_all | T2 | 1 | 4 | 4 | 1 | 25% |" in text
    assert "| arslan | m | ask_risky | T3 | 1 | 0 | 0 | 0 | – |" in text         # no calls: no share, not 0%
    assert "T4" not in text and "codex" not in text


def test_a_run_outside_arslans_sandbox_prints_no_share():
    assert bench_report.sandbox_cards([_record("T4", "ask_risky", None, 3, 3)]) == {}
    assert "| arslan" not in bench_report.render_sandbox_cards([_record("T4", "ask_risky", None, 3, 3)])
