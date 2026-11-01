"""INB7-c4c (v0.1.64): board F's 「应用」 chip over 「最近的工作」: the runs that used Mac apps (Hands). A run is in it when a Hands call
carries its id (#632), never by time, since runs overlap and a call can be logged late; an older call with no id falls back to its
conversation and the run's window. The trace is faked: hands_service.read_trace is what the chip reads."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from server.db.models import Run
from server.services import approvals, hands_service

T = datetime(2026, 10, 30, 9, 0, 0)                       # naive UTC, as runs are stored


def _run(message: str, conversation: str, start_min: int, end_min: int | None, **kw) -> Run:
    return Run(conversation_id=conversation, spawn_name="Arslan", user_message=message, kind="host", task_tokens=0,
               status="recorded" if end_min is not None else "recording", created_at=T + timedelta(minutes=start_min),
               ended_at=T + timedelta(minutes=end_min) if end_min is not None else None, **kw)


def _at(minutes: int) -> str:
    return (T + timedelta(minutes=minutes)).replace(tzinfo=timezone.utc).isoformat(timespec="seconds")


async def _seed(client, monkeypatch) -> dict[str, int]:
    """Two overlapping runs in one conversation (a: 0–10 min, b: 5–20 min), a run in another conversation, an older run whose call
    has no id, a run with no Hands at all, and one still running."""
    monkeypatch.setattr(approvals, "all_pending", lambda: [])
    async with client.db_maker() as db:
        named = {"a": _run("a", "c", 0, 10), "b": _run("b", "c", 5, 20), "other": _run("other", "d", 0, 10),
                 "old": _run("old", "e", 30, 40), "none": _run("none", "c", 60, 70), "live": _run("live", "f", 80, None)}
        db.add_all(named.values())
        await db.commit()
        ids = {name: run.id for name, run in named.items()}
    trace = [
        {"at": _at(25), "conversation": "c", "run_id": ids["a"], "op": "click", "outcome": "ok"},   # a's, logged after a ended
        {"at": _at(15), "conversation": "c", "run_id": ids["a"], "op": "look", "outcome": "ok"},    # a's, inside b's window: not b's
        {"at": _at(7), "conversation": "d", "run_id": ids["other"], "op": "look", "outcome": "ok"},
        {"at": _at(35), "conversation": "e", "run_id": None, "op": "look", "outcome": "ok"},        # no id: e's window → old
        {"at": _at(65), "conversation": "z", "run_id": None, "op": "look", "outcome": "ok"},        # no id, no run there
        {"at": _at(90), "conversation": "f", "run_id": None, "op": "look", "outcome": "ok"},        # no id, a run still going
    ]
    monkeypatch.setattr(hands_service, "read_trace", lambda *a, **k: trace)
    return ids


async def _listed(client, **params) -> list[str]:
    return [row["user_message"] for row in (await client.get("/api/v1/runs", params={"limit": 50, **params})).json()]


async def test_the_apps_chip_lists_the_runs_a_hands_call_names_and_falls_back_to_the_window_without_an_id(client, monkeypatch):
    await _seed(client, monkeypatch)
    # a: by its id though the call came after it ended, and b, which overlaps it in the same conversation, is not in by time.
    assert await _listed(client, used="apps") == ["live", "old", "other", "a"]
    assert await _listed(client, used="apps", limit=2) == ["live", "old"]
    assert (await client.get("/api/v1/runs", params={"used": "everything"})).status_code == 422


async def test_the_count_agrees_with_the_list(client, monkeypatch):
    await _seed(client, monkeypatch)
    counts = (await client.get("/api/v1/runs/counts")).json()
    assert counts["apps"] == 4


async def test_no_trace_lists_none(client, monkeypatch):
    await _seed(client, monkeypatch)
    monkeypatch.setattr(hands_service, "read_trace", lambda *a, **k: [])
    assert await _listed(client, used="apps") == []
    assert (await client.get("/api/v1/runs/counts")).json()["apps"] == 0


async def test_an_unreadable_entry_is_skipped_not_fatal(client, monkeypatch):
    ids = await _seed(client, monkeypatch)
    monkeypatch.setattr(hands_service, "read_trace", lambda *a, **k: [
        "not a dict", {"run_id": "7"}, {"run_id": None, "conversation": "e", "at": "yesterday"},
        {"run_id": ids["other"], "at": _at(7)}])
    assert await _listed(client, used="apps") == ["other"]
