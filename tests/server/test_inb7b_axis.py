"""INB7-b (v0.1.64): Progress's one time axis (board F). A run's bar says when it ran, for how long and how it ended, amber
while it waits for your answer; a picked run's steps sit on the axis at the time each one started, for the replay."""
from __future__ import annotations

from datetime import datetime

from server.db.models import ArslanMessage, Run, RunStep
from server.services import approvals


def _run(conversation_id: str, status: str, **kw) -> Run:
    return Run(**{"conversation_id": conversation_id, "spawn_name": "Arslan", "user_message": "x", "status": status, "kind": "host",
                  "task_tokens": 0, **kw})


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


async def test_a_run_the_boot_sweep_interrupted_says_when_it_ended(client):
    # run_reaper.mark_interrupted_runs sets ended_at and no total: the bar must end there, not run on to now.
    async with client.db_maker() as db:
        db.add_all([_run("c", "interrupted", ended_at=datetime(2026, 11, 1, 3, 30)), _run("c", "recording")])
        await db.commit()
    rows = sorted((await client.get("/api/v1/runs?limit=10")).json(), key=lambda row: row["id"])
    assert [(row["status"], row["total_ms"], row["ended_at"]) for row in rows] == [
        ("interrupted", None, "2026-11-01T03:30:00"), ("recording", None, None)]


async def test_where_a_turn_came_from_is_still_its_own_message_when_many_turns_are_asked_about_at_once(client):
    """The axis asks for up to 200 runs every 30 seconds, so the phone lookup reads each conversation once, not once per run
    (⓪Plan's review of PR 622, 8). Same answers as before: the turn's own message, skipping one read mid-turn (K9b tags it)."""
    async with client.db_maker() as db:
        runs = [_run(conv, "recorded", user_message=f"{conv}{i}") for conv, i in (("p", 1), ("p", 2), ("p", 3), ("q", 1))]
        db.add_all(runs)
        await db.flush()
        p1, p2, p3, q1 = (run.id for run in runs)
        db.add_all([
            ArslanMessage(conversation_id="p", role="user", content="from the phone", source="phone"),
            ArslanMessage(conversation_id="p", role="arslan", content="a", run_id=p1),
            ArslanMessage(conversation_id="p", role="user", content="typed"),
            ArslanMessage(conversation_id="p", role="user", content="read mid-turn", source="phone", run_id=p2),
            ArslanMessage(conversation_id="p", role="arslan", content="b", run_id=p2),
            ArslanMessage(conversation_id="p", role="user", content="from the phone again", source="phone"),
            ArslanMessage(conversation_id="p", role="arslan", content="c", run_id=p3),
            ArslanMessage(conversation_id="q", role="user", content="typed in q"),
            ArslanMessage(conversation_id="q", role="arslan", content="d", run_id=q1),
        ])
        await db.commit()
    origin = {row["user_message"]: row["origin"] for row in (await client.get("/api/v1/runs?limit=10")).json()}
    assert origin == {"p1": "phone", "p2": "chat", "p3": "phone", "q1": "chat"}
