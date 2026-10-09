"""0.1.58 §1: what a reply did, folded — narration kept with the step it introduced, the
footer row on history rows, the opened list in plain data, raw only when asked for."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from server.db.models import ArslanMessage, Run, RunStep
from server.services import run_process
from server.services.run_recorder import RunRecorder

ROOT = Path(__file__).resolve().parents[2]


def _recorder(events):
    rec = RunRecorder(run_id=1, started_at=datetime(2026, 10, 9, 12), route_ms=None, spawn_name="Arslan", kind="host")
    t = datetime(2026, 10, 9, 12)
    rec._events = [(t + timedelta(seconds=i), ev) for i, ev in enumerate(events)]
    return rec


def test_narration_rides_on_the_tool_call_it_introduced():
    steps = _recorder([
        {"type": "note", "text": "Let me look at the downloads first."},
        {"type": "tool_call", "tool": "list_dir", "args_summary": "{}"},
        {"type": "tool_result", "tool": "list_dir", "ok": True, "summary": "ok"},
        {"type": "tool_call", "tool": "read_file", "args_summary": "{}"},
        {"type": "tool_result", "tool": "read_file", "ok": True, "summary": "ok"},
        {"type": "note", "text": "Now the table."},
        {"type": "tool_call", "tool": "run_python", "args_summary": "{}"},
    ])._derive_steps("answer")
    calls = [s for s in steps if s["kind"] == "tool_call"]
    assert [s["detail"].get("narration") for s in calls] == ["Let me look at the downloads first.", None, "Now the table."]
    assert {s["kind"] for s in steps} <= {"tool_call", "dispatch", "route", "escalation"}     # no new step kind


def _step(seq, tool, ok, detail, ms=100, run_id=1):
    return RunStep(run_id=run_id, seq=seq, kind="tool_call", ref={"tool": tool, "ok": ok}, detail=detail, duration_ms=ms)


def test_entries_are_plain_data_in_order_and_raw_only_when_asked():
    steps = [
        _step(0, "web_search", True, {"narration": "Searching.", "args_summary": '{"query": "tide tables"}',
              "args_full": '{"query": "tide tables"}', "summary": "2 results · provider=x",
              "result_raw": json.dumps({"ok": True, "provider": "x", "results": [
                  {"title": "A", "url": "https://a.example"}, {"title": "B", "url": "https://b.example"}]})}),
        _step(1, "start_background_work", True, {"args_summary": "{}", "summary": "ok"}),
        _step(2, "run_command", False, {"args_full": '{"command": "ls -la"}', "summary": "exit 2",
              "result_raw": json.dumps({"ok": False, "error": "exit 2", "exit_code": 2,
                                        "stdout": "\n".join(f"line {i}" for i in range(9))})}),
        _step(3, "mcp_7_read_data", True, {"args_full": '{"file": "a.xlsx", "sheet": "S"}',
              "result_raw": json.dumps({"ok": True, "content": [{"type": "text", "text": "rows: 13"}]})}),
    ]
    out = run_process.entries(steps, raw=False)
    assert [e["kind"] for e in out] == ["note", "tool", "tool", "tool"]       # the job tool is the job card's
    search, command, mcp = out[1]["detail"], out[2]["detail"], out[3]["detail"]
    assert search["view"] == "search" and search["query"] == "tide tables"
    assert [link["url"] for link in search["links"]] == ["https://a.example", "https://b.example"]
    assert command["view"] == "command" and command["command"] == "ls -la" and command["exit_code"] == 2
    assert command["head"] == {"lines": [f"line {i}" for i in range(5)], "more": 4}
    assert command["error"] == "exit 2"
    assert mcp["view"] == "mcp" and mcp["args"] == [["file", "a.xlsx"], ["sheet", "S"]] and mcp["head"]["lines"] == ["rows: 13"]
    assert all("raw" not in e for e in out)
    assert "raw" in run_process.entries(steps, raw=True)[1]


def test_a_truncated_raw_result_falls_back_instead_of_failing():
    step = _step(0, "web_search", True, {"args_summary": '{"query": "x"}', "args_full": '{"query": "x"',
                                          "result_raw": '{"ok": true, "results": [{"title": "A", "url'})
    detail = run_process.entries([step], raw=False)[0]["detail"]
    assert detail["view"] == "search" and detail["query"] == "x" and detail["links"] == []


def test_counts_leave_out_successful_job_tools_but_not_failed_ones():
    assert run_process.counts([("read_file", True), ("background_status", True), ("stop_background_work", False),
                               ("run_command", False)]) == (3, 2)


async def test_history_rows_carry_the_footer_row(client, monkeypatch):
    async with client.db_maker() as db:
        run = Run(conversation_id="c", spawn_name="Arslan", user_message="x", status="recorded", kind="host",
                  task_tokens=40_000, total_ms=48_000, model="deepseek-v4-flash", provider="deepseek",
                  tokens_in=38_000, tokens_out=2_000)
        db.add(run)
        await db.flush()
        db.add_all([_step(0, "read_file", True, {}, run_id=run.id), _step(1, "run_command", False, {}, run_id=run.id),
                    RunStep(run_id=run.id, seq=2, kind="dispatch", ref={}, detail={})])
        db.add_all([ArslanMessage(conversation_id="c", role="user", content="x"),
                    ArslanMessage(conversation_id="c", role="arslan", content="done", run_id=run.id)])
        await db.commit()
        run_id = run.id
    from server.db import session as db_session
    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    from server.ws.arslan import _history
    rows = await _history("c")
    assert "process" not in rows[0]
    proc = rows[1]["process"]
    assert (proc["steps"], proc["failed"], proc["ms"]) == (2, 1, 48_000)
    assert proc["usage"]["models"] == [{"model": "deepseek-v4-flash", "provider": "deepseek"}]
    assert proc["usage"]["usd"] is not None
    body = (await client.get(f"/api/v1/runs/{run_id}/process")).json()
    assert body["steps"] == 2 and [e["tool"] for e in body["entries"]] == ["read_file", "run_command"]
    assert all("raw" not in e for e in body["entries"])


async def test_raw_appears_only_with_the_setting(client):
    from server.services import settings_service
    async with client.db_maker() as db:
        run = Run(conversation_id="c", spawn_name="Arslan", user_message="x", status="recorded", kind="host", task_tokens=0)
        db.add(run)
        await db.flush()
        db.add(RunStep(run_id=run.id, seq=0, kind="tool_call", ref={"tool": "read_file", "ok": True},
                       detail={"args_full": '{"path": "a"}', "result_raw": '{"ok": true}'}))
        await settings_service._set_raw(db, "show_technical_details", "true")
        await db.commit()
        run_id = run.id
    entry = (await client.get(f"/api/v1/runs/{run_id}/process")).json()["entries"][0]
    assert entry["raw"] == {"args": '{"path": "a"}', "result": '{"ok": true}'}
    assert (await client.get("/api/v1/runs/999999/process")).status_code == 404


def test_the_job_tool_list_matches_the_client():
    store = (ROOT / "web/src/stores/arslanStore.ts").read_text()
    names = set(re.search(r"const JOB_TOOLS = new Set\(\[([^\]]*)\]\)", store).group(1).replace('"', "").replace(" ", "").split(","))
    assert names == set(run_process.JOB_TOOLS)
