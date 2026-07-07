"""Tests for GET /api/v1/runs/catalog — per-spawn RED aggregation (Task 2 of the
agent diagnosis dashboard plan)."""
from __future__ import annotations

from datetime import datetime, timedelta

from server.db.models import Run


async def test_catalog_aggregates_red_health_and_sorts_worst_first(client):
    async with client.db_maker() as db:
        # spawn "Bad": 3 runs, 1 errored, all scored low (<4).
        for i in range(3):
            db.add(Run(
                conversation_id="c", spawn_id=1, spawn_name="Bad",
                user_message=f"bad {i}", status="scored", task_tokens=100,
                total_ms=500 + i * 10, overall_score=2.0, overall_badge="bad",
                error_kind="timeout" if i == 0 else None,
            ))
        # spawn "Good": 3 runs, no errors, all scored high (>=8).
        for i in range(3):
            db.add(Run(
                conversation_id="c", spawn_id=2, spawn_name="Good",
                user_message=f"good {i}", status="scored", task_tokens=50,
                total_ms=200 + i * 10, overall_score=9.0, overall_badge="good",
                error_kind=None,
            ))
        await db.commit()

    resp = await client.get("/api/v1/runs/catalog", params={"range": "all"})
    assert resp.status_code == 200
    body = resp.json()

    assert set(body["fleet"]) >= {"run_count", "error_ratio", "p95_ms", "pass_rate", "tokens_sum"}

    names = [s["spawn_name"] for s in body["spawns"]]
    assert names[0] == "Bad"  # worst (red) first

    bad = body["spawns"][0]
    assert bad["health"] == "red"
    assert 0 < bad["error_ratio"] <= 1
    assert isinstance(bad["score_trend"], list)

    good = next(s for s in body["spawns"] if s["spawn_name"] == "Good")
    assert good["health"] == "green"


async def test_catalog_range_window_filters(client):
    async with client.db_maker() as db:
        old_run = Run(
            conversation_id="c", spawn_id=1, spawn_name="Old",
            user_message="old", status="scored", task_tokens=10,
            total_ms=100, overall_score=8.0, overall_badge="good",
        )
        db.add(old_run)
        await db.commit()
        await db.refresh(old_run)
        old_run.created_at = datetime.utcnow() - timedelta(hours=40)
        db.add(old_run)
        await db.commit()

        db.add(Run(
            conversation_id="c", spawn_id=2, spawn_name="Recent",
            user_message="recent", status="scored", task_tokens=10,
            total_ms=100, overall_score=8.0, overall_badge="good",
        ))
        await db.commit()

    now24 = (await client.get("/api/v1/runs/catalog", params={"range": "24h"})).json()
    allr = (await client.get("/api/v1/runs/catalog", params={"range": "all"})).json()

    assert now24["fleet"]["run_count"] < allr["fleet"]["run_count"]


async def test_runs_catalog_route_order(client):
    """GET /runs/catalog must hit the catalog route, not /runs/{run_id} (422)."""
    resp = await client.get("/api/v1/runs/catalog", params={"range": "all"})
    assert resp.status_code == 200


async def test_catalog_empty(client):
    body = (await client.get("/api/v1/runs/catalog", params={"range": "all"})).json()
    assert body["fleet"]["run_count"] == 0
    assert body["fleet"]["error_ratio"] == 0.0
    assert body["fleet"]["p95_ms"] is None
    assert body["fleet"]["pass_rate"] is None
    assert body["fleet"]["tokens_sum"] == 0
    assert body["spawns"] == []
