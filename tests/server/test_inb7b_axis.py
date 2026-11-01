"""INB7-b (v0.1.64): Progress's one time axis (board F). A run's bar says when it ran, for how long and how it ended, amber
while it waits for your answer; a picked run's steps sit on the axis at the time each one started, for the replay."""
from __future__ import annotations

from datetime import datetime

from server.db.models import Run, RunStep
from server.services import approvals


def _run(conversation_id: str, status: str, **kw) -> Run:
    return Run(conversation_id=conversation_id, spawn_name="Arslan", user_message="x", status=status, kind="host",
               task_tokens=0, **kw)


async def test_a_running_run_waits_on_you_only_while_its_conversation_has_an_open_card(client, monkeypatch):
    # A card with no conversation (a scheduled run's, say) marks nothing.
    monkeypatch.setattr(approvals, "all_pending", lambda: [{"call_id": "c1", "conversation_id": "asking"}, {"call_id": "c2"}])
    async with client.db_maker() as db:
        db.add_all([_run("asking", "recording"), _run("asking", "recorded"), _run("quiet", "recording"),
                    _run("asking", "failed")])
        await db.commit()
    rows = sorted((await client.get("/api/v1/runs?limit=10")).json(), key=lambda row: row["id"])
    assert [(row["status"], row["waiting"]) for row in rows] == [
        ("recording", True), ("recorded", False), ("recording", False), ("failed", False)]


async def test_each_step_says_when_it_started_and_the_run_says_when_it_ran(client):
    async with client.db_maker() as db:
        done = _run("c", "recorded", started_at=datetime(2026, 11, 1, 9, 0, 0), ended_at=datetime(2026, 11, 1, 9, 2, 30),
                    total_ms=150_000)
        running = _run("c", "recording", started_at=datetime(2026, 11, 1, 9, 5, 0))
        db.add_all([done, running])
        await db.flush()
        db.add_all([
            RunStep(run_id=done.id, seq=0, kind="tool_call", ref={"tool": "read_file", "ok": True}, detail={},
                    started_at=datetime(2026, 11, 1, 9, 0, 5)),
            RunStep(run_id=done.id, seq=1, kind="tool_call", ref={"tool": "run_command", "ok": False}, detail={},
                    started_at=datetime(2026, 11, 1, 9, 1, 40)),
            # A row written before steps kept their time: listed, with no place on the axis.
            RunStep(run_id=done.id, seq=2, kind="tool_call", ref={"tool": "list_dir", "ok": True}, detail={}),
        ])
        await db.commit()
        done_id, running_id = done.id, running.id
    body = (await client.get(f"/api/v1/runs/{done_id}/process")).json()
    assert (body["started_at"], body["ended_at"]) == ("2026-11-01T09:00:00Z", "2026-11-01T09:02:30Z")
    assert [(e["tool"], e["at"]) for e in body["entries"]] == [
        ("read_file", "2026-11-01T09:00:05Z"), ("run_command", "2026-11-01T09:01:40Z"), ("list_dir", None)]
    still = (await client.get(f"/api/v1/runs/{running_id}/process")).json()
    assert (still["started_at"], still["ended_at"], still["entries"]) == ("2026-11-01T09:05:00Z", None, [])
