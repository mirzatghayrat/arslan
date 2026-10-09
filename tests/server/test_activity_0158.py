"""0.1.58 §7 Activity: where each run came from, the list's filters and paging, the
judgments' paging, and what a chart slice's hover card says."""
from __future__ import annotations

from datetime import datetime, timedelta

from server.api.usage import run_activity
from server.db.models import ArslanMessage, Judgment, Run


async def _runs(client, *rows):
    async with client.db_maker() as db:
        objs = [Run(conversation_id=r.get("conv", "c"), spawn_name=r.get("name", "Arslan"),
                    user_message=r.get("msg", "x"), status="recorded", kind=r.get("kind", "host"),
                    task_tokens=r.get("tokens", 0), total_ms=100, model=r.get("model"),
                    created_at=r.get("at", datetime.utcnow())) for r in rows]
        db.add_all(objs)
        await db.commit()
        for o in objs:
            await db.refresh(o)
        return [o.id for o in objs]


async def test_origin_of_each_run(client):
    chat, job, sched, browser, phone = await _runs(
        client, {"msg": "chat"}, {"msg": "job"}, {"msg": "sched", "kind": "scheduled"},
        {"msg": "browser", "name": "Browser preview"}, {"msg": "phone", "conv": "p"})
    async with client.db_maker() as db:
        db.add_all([
            ArslanMessage(conversation_id="c", role="user", content="chat"),
            ArslanMessage(conversation_id="c", role="arslan", content="a", run_id=chat),
            ArslanMessage(conversation_id="c", role="arslan", content="done", run_id=job, job_outcome="done"),
            ArslanMessage(conversation_id="p", role="user", content="from phone", source="phone"),
            ArslanMessage(conversation_id="p", role="arslan", content="a", run_id=phone),
        ])
        await db.commit()
    body = (await client.get("/api/v1/runs")).json()
    origin = {item["user_message"]: item["origin"] for item in body}
    assert origin == {"chat": "chat", "job": "job", "sched": "scheduled", "browser": "browser", "phone": "phone"}


async def test_phone_origin_is_the_turns_own_message(client):
    """A conversation that once had a phone message: a later turn typed in the window is chat."""
    first, second = await _runs(client, {"msg": "first", "conv": "p"}, {"msg": "second", "conv": "p"})
    async with client.db_maker() as db:
        db.add_all([
            ArslanMessage(conversation_id="p", role="user", content="from phone", source="phone"),
            ArslanMessage(conversation_id="p", role="arslan", content="a", run_id=first),
            ArslanMessage(conversation_id="p", role="user", content="typed"),
            ArslanMessage(conversation_id="p", role="arslan", content="b", run_id=second),
        ])
        await db.commit()
    origin = {i["user_message"]: i["origin"] for i in (await client.get("/api/v1/runs")).json()}
    assert origin == {"first": "phone", "second": "chat"}


async def test_list_pages_back_and_filters_by_span_and_model(client):
    now = datetime.utcnow()
    ids = await _runs(client, *[{"msg": f"r{i}", "model": "m-a" if i % 2 else "m-b",
                                 "at": now - timedelta(hours=10 - i), "tokens": 7} for i in range(6)])
    page1 = (await client.get("/api/v1/runs", params={"limit": 2})).json()
    assert [r["id"] for r in page1] == [ids[5], ids[4]]
    page2 = (await client.get("/api/v1/runs", params={"limit": 2, "before_id": page1[-1]["id"]})).json()
    assert [r["id"] for r in page2] == [ids[3], ids[2]]
    span = (await client.get("/api/v1/runs", params={
        "since": (now - timedelta(hours=8, minutes=30)).isoformat(),
        "until": (now - timedelta(hours=6, minutes=30)).isoformat()})).json()
    assert sorted(r["user_message"] for r in span) == ["r2", "r3"]
    by_model = (await client.get("/api/v1/runs", params={"model": "m-a"})).json()
    assert sorted(r["user_message"] for r in by_model) == ["r1", "r3", "r5"]
    assert {r["model"] for r in by_model} == {"m-a"} and {r["tokens"] for r in by_model} == {7}


async def test_scheduled_runs_are_listed(client):
    await _runs(client, {"msg": "fire", "kind": "scheduled"}, {"msg": "arm", "kind": "replay"})
    msgs = [r["user_message"] for r in (await client.get("/api/v1/runs")).json()]
    assert msgs == ["fire"]


async def test_judgments_page_back_by_id(client):
    async with client.db_maker() as db:
        rows = [Judgment(point="memory.worth", mode="shadow", state={}, state_hash="h") for _ in range(5)]
        db.add_all(rows)
        await db.commit()
        ids = sorted(r.id for r in rows)
    first = (await client.get("/api/v1/judgments", params={"limit": 2})).json()["items"]
    assert [r["id"] for r in first] == [ids[4], ids[3]]
    rest = (await client.get("/api/v1/judgments", params={"limit": 10, "before_id": ids[3]})).json()["items"]
    assert [r["id"] for r in rest] == [ids[2], ids[1], ids[0]]


def test_slice_hover_card_facts():
    now = datetime(2026, 10, 9, 12, 0)
    since = now - timedelta(hours=24)
    t = now - timedelta(minutes=30)
    runs = [("recorded", 1_000, t), ("recorded", 9_000, t), ("failed", 4_000, t)]
    items = [("answer", "deepseek", "deepseek-v4-flash", 1000, 200, False, 1200, t),
             ("answer", "deepseek", "deepseek-v4-flash", 500, 100, False, 600, t),
             ("answer", "openrouter", "other/model", 10, 10, True, 20, t)]
    _, bins = run_activity(runs, items, since, now, "24h")
    last = bins[-1]
    assert (last.runs, last.failed, last.p50_ms, last.max_ms) == (3, 1, 4_000, 9_000)
    assert last.models == [{"model": "deepseek-v4-flash", "tokens": 1800}, {"model": "other/model", "tokens": 20}]
    assert last.usd is not None and last.usd > 0       # the estimated item is never priced
    assert bins[0].usd is None and bins[0].models == [] and bins[0].p50_ms is None
