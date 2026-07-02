"""Tests for GET /api/v1/runs/{id} — run replay + evaluation endpoint."""
from __future__ import annotations

import pytest

from server.db.models import Run, RunEvaluation, RunStep


async def test_get_run_returns_steps_and_eval(client):
    async with client.db_maker() as db:
        run = Run(conversation_id="c1", spawn_name="Mermer", user_message="x",
                  status="scored", task_tokens=42, total_ms=1500,
                  overall_score=8.0, overall_badge="good")
        db.add(run)
        await db.commit()
        await db.refresh(run)
        db.add(RunStep(run_id=run.id, seq=0, kind="route", ref={"spawn_name": "Mermer"},
                       detail={}, duration_ms=80))
        db.add(RunEvaluation(run_id=run.id, dimension="routing", status="pass",
                             score=9.0, comment="选对了人"))
        await db.commit()
        run_id = run.id

    resp = await client.get(f"/api/v1/runs/{run_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run"]["status"] == "scored"
    assert body["run"]["overall_badge"] == "good"
    assert body["steps"][0]["kind"] == "route"
    assert body["evaluations"][0]["dimension"] == "routing"


async def test_get_missing_run_404(client):
    resp = await client.get("/api/v1/runs/9999")
    assert resp.status_code == 404


async def test_list_runs_returns_recent_desc_and_filters(client):
    async with client.db_maker() as db:
        for i, sid in enumerate([1, 1, 2]):
            db.add(Run(conversation_id="c", spawn_id=sid, spawn_name=f"S{sid}",
                       user_message=f"task {i}", status="scored", task_tokens=0,
                       total_ms=100, overall_score=8.0, overall_badge="good"))
        await db.commit()

    r = await client.get("/api/v1/runs")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3
    assert body[0]["id"] > body[1]["id"]
    assert {"id", "spawn_name", "status", "overall_score", "overall_badge",
            "total_ms", "user_message"} <= set(body[0])

    r2 = await client.get("/api/v1/runs", params={"spawn_id": 2})
    assert [item["spawn_name"] for item in r2.json()] == ["S2"]

    r3 = await client.get("/api/v1/runs", params={"limit": 1})
    assert len(r3.json()) == 1


async def test_runs_summary_route_order(client):
    """GET /runs/summary must hit the summary route, not /runs/{run_id} (422)."""
    resp = await client.get("/api/v1/runs/summary")
    assert resp.status_code == 200


async def test_runs_summary_empty(client):
    body = (await client.get("/api/v1/runs/summary")).json()
    assert body["scored_count"] == 0
    assert body["avg_score"] is None
    assert body["pass_rate"] is None
    assert body["dimension_averages"] == {
        "routing": None, "fabrication": None, "identity": None, "completion": None,
    }
    assert body["per_spawn"] == []
    assert body["recent"] == []


async def test_runs_summary_aggregates(client):
    async with client.db_maker() as db:
        r1 = Run(conversation_id="c", spawn_name="Mermer", user_message="a",
                 status="scored", task_tokens=0, total_ms=100,
                 overall_score=8.0, overall_badge="good")
        r2 = Run(conversation_id="c", spawn_name="Mermer", user_message="b",
                 status="scored", task_tokens=0, total_ms=100,
                 overall_score=6.0, overall_badge="ok")
        r3 = Run(conversation_id="c", spawn_name="小美", user_message="c",
                 status="scored", task_tokens=0, total_ms=100,
                 overall_score=9.0, overall_badge="good")
        r4 = Run(conversation_id="c", spawn_name="小美", user_message="d",
                 status="recorded", task_tokens=0, total_ms=100)  # unscored
        db.add_all([r1, r2, r3, r4])
        await db.commit()
        for r in (r1, r2, r3, r4):
            await db.refresh(r)
        db.add(RunEvaluation(run_id=r1.id, dimension="routing", status="pass",
                             score=9.0, comment=""))
        db.add(RunEvaluation(run_id=r2.id, dimension="routing", status="warn",
                             score=5.0, comment=""))
        db.add(RunEvaluation(run_id=r1.id, dimension="completion", status="pass",
                             score=8.0, comment=""))
        # Evaluation attached to an UNSCORED run must not pollute the averages.
        db.add(RunEvaluation(run_id=r4.id, dimension="routing", status="pass",
                             score=1.0, comment=""))
        await db.commit()
        unscored_id = r4.id

    body = (await client.get("/api/v1/runs/summary")).json()
    assert body["scored_count"] == 3
    assert body["avg_score"] == pytest.approx(7.67, abs=0.01)
    assert body["pass_rate"] == 67  # 2 of 3 scored runs >= 7

    assert body["dimension_averages"]["routing"] == 7.0  # (9+5)/2, r4's 1.0 excluded
    assert body["dimension_averages"]["completion"] == 8.0
    assert body["dimension_averages"]["fabrication"] is None
    assert body["dimension_averages"]["identity"] is None

    per = {p["spawn_name"]: p for p in body["per_spawn"]}
    assert per["Mermer"]["scored_count"] == 2
    assert per["Mermer"]["avg_score"] == 7.0
    assert per["Mermer"]["pass_rate"] == 50
    assert per["小美"]["scored_count"] == 1
    assert per["小美"]["pass_rate"] == 100
    assert body["per_spawn"][0]["spawn_name"] == "Mermer"  # scored_count desc

    ids = [p["id"] for p in body["recent"]]
    assert ids == sorted(ids)  # ascending by id
    unscored = next(p for p in body["recent"] if p["id"] == unscored_id)
    assert unscored["overall_score"] is None  # unscored included with null score
