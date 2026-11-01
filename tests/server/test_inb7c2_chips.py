"""INB7-c2 (v0.1.64): board F's chips over 「最近的工作」 (要你做, 失败, 定时, 手机), filtered on the server so a paged list and
its counts agree. The phone's own reads (/phone/runs) are not touched."""
from __future__ import annotations

from datetime import datetime, timedelta

from server.db.models import ArslanMessage, Run, ScheduledTask, ScheduledTaskRun
from server.services import approvals


def _run(conversation_id: str, status: str = "recorded", **kw) -> Run:
    return Run(**{"conversation_id": conversation_id, "spawn_name": "Arslan", "user_message": "x", "status": status,
                  "kind": "host", "task_tokens": 0, **kw})


async def _seed(client) -> dict[str, int]:
    """A typed chat run, a failed one, a scheduled fire, a run waiting on a card, one running with none, and three turns sent from the phone into one
    conversation, between two typed ones there."""
    async with client.db_maker() as db:
        named = {"typed": _run("c", user_message="typed"), "failed": _run("c", "failed", user_message="failed"),
                 "fire": _run("scheduled-4", kind="scheduled", user_message="fire"),
                 "asking": _run("asking", "recording", user_message="asking"),
                 "busy": _run("c", "recording", user_message="busy"),            # running, no card: not waiting on you
                 "asked": _run("asking", user_message="asked")}                   # ended, in the asking conversation
        # Since C1 (0.1.63) a fire is a host turn in the task's conversation, linked only by scheduled_task_runs.run_id
        # (⓪Plan's review of PR 627).
        named["c1fire"] = _run("scheduled-5", user_message="c1fire")
        db.add_all(named.values())
        await db.flush()
        task = ScheduledTask(name="digest", prompt="sum up", schedule_kind="interval", interval_s=86_400)
        db.add(task)
        await db.flush()
        db.add_all([ScheduledTaskRun(task_id=task.id, run_id=named["c1fire"].id, outcome="ok"),
                    ScheduledTaskRun(task_id=task.id, run_id=None, outcome="skipped_overlap")])
        for i in range(5):
            run = _run("p", user_message=f"p{i}")
            db.add(run)
            await db.flush()
            named[f"p{i}"] = run
            phone = i in (0, 2, 4)
            db.add_all([ArslanMessage(conversation_id="p", role="user", content=f"ask {i}", source="phone" if phone else None),
                        ArslanMessage(conversation_id="p", role="arslan", content=f"answer {i}", run_id=run.id)])
        await db.commit()
        return {name: run.id for name, run in named.items()}


async def _listed(client, **params) -> list[str]:
    return [row["user_message"] for row in (await client.get("/api/v1/runs", params={"limit": 50, **params})).json()]


async def test_each_chip_lists_only_its_runs(client, monkeypatch):
    monkeypatch.setattr(approvals, "all_pending", lambda: [{"call_id": "c1", "conversation_id": "asking"}])
    await _seed(client)
    assert await _listed(client, outcome="failed") == ["failed"]
    assert await _listed(client, outcome="waiting") == ["asking"]
    assert await _listed(client, origin="scheduled") == ["c1fire", "fire"]
    assert await _listed(client, origin="phone") == ["p4", "p2", "p0"]                  # newest first, typed turns left out
    assert await _listed(client, origin="phone", limit=1) == ["p4"]                     # a page holds no more than asked
    assert (await client.get("/api/v1/runs", params={"outcome": "later"})).status_code == 422


async def test_a_c1_fire_is_listed_as_scheduled(client, monkeypatch):
    monkeypatch.setattr(approvals, "all_pending", lambda: [])
    await _seed(client)
    origin = {row["user_message"]: row["origin"] for row in (await client.get("/api/v1/runs", params={"limit": 50})).json()}
    assert (origin["c1fire"], origin["fire"], origin["typed"]) == ("scheduled", "scheduled", "chat")


async def test_the_phone_chip_pages_back_like_the_rest(client, monkeypatch):
    # Phone turns are found after the query (where a turn came from is read from its messages), so a page still holds `limit`
    # of them and the next one starts below the last.
    monkeypatch.setattr(approvals, "all_pending", lambda: [])
    from server.api import runs as runs_api
    monkeypatch.setattr(runs_api, "_PHONE_BATCH", 2)                                  # several batches per page
    ids = await _seed(client)
    first = (await client.get("/api/v1/runs", params={"origin": "phone", "limit": 2})).json()
    assert [row["user_message"] for row in first] == ["p4", "p2"]
    rest = await _listed(client, origin="phone", limit=2, before_id=first[-1]["id"])
    assert rest == ["p0"] and ids["p0"] < ids["p2"]


async def test_the_counts_follow_the_same_scope(client, monkeypatch):
    monkeypatch.setattr(approvals, "all_pending", lambda: [{"call_id": "c1", "conversation_id": "asking"}])
    await _seed(client)
    assert (await client.get("/api/v1/runs/counts")).json() == {"waiting": 1, "failed": 1, "scheduled": 2, "phone": 3}
    later = (datetime.utcnow() + timedelta(minutes=5)).isoformat()
    assert (await client.get("/api/v1/runs/counts", params={"since": later})).json() == {
        "waiting": 0, "failed": 0, "scheduled": 0, "phone": 0}
    async with client.db_maker() as db:
        db.add(_run("c", "failed", model="claude-sonnet-5-5"))
        await db.commit()
    assert (await client.get("/api/v1/runs/counts", params={"model": "claude-sonnet-5-5"})).json()["failed"] == 1


async def test_the_phones_own_run_read_is_unchanged(client, monkeypatch):
    """⓪Plan: the chips must leave /phone/runs and the Bridge's shapes alone. The keys the Bridge reads are pinned here."""
    monkeypatch.setattr(approvals, "all_pending", lambda: [])
    ids = await _seed(client)
    body = (await client.get(f"/api/v1/phone/runs/{ids['p0']}")).json()
    assert sorted(body) == PHONE_RUN_KEYS
    assert (await client.get(f"/api/v1/phone/runs/{ids['p0']}", params={"origin": "phone", "outcome": "failed"})).json() == body


PHONE_RUN_KEYS = sorted(["run_id", "conversation_id", "title", "state", "started_at", "duration_ms", "total", "steps", "files"])
