"""Tests for GET /api/v1/runs/anomalies — deterministic threshold rules (Task 3 of the
agent diagnosis dashboard plan)."""
from __future__ import annotations

from server.db.models import Run, RunEvaluation


async def test_anomalies_flags_high_error_and_fabrication(client):
    async with client.db_maker() as db:
        # spawn "Bad": 4 runs, 2 errored (50% > ERR_RED=0.15), and the last two
        # runs each have a failing "fabrication" RunEvaluation (streak >= 2).
        runs = []
        for i in range(4):
            r = Run(
                conversation_id="c", spawn_id=1, spawn_name="Bad",
                user_message=f"bad {i}", status="scored", task_tokens=100,
                total_ms=500 + i * 10, overall_score=2.0, overall_badge="bad",
                error_kind="timeout" if i < 2 else None,
            )
            db.add(r)
            runs.append(r)
        await db.commit()
        for r in runs:
            await db.refresh(r)

        for r in runs[2:]:
            db.add(RunEvaluation(
                run_id=r.id, dimension="fabrication", status="fail",
                score=1.0, comment="made it up",
            ))
        await db.commit()

    resp = await client.get("/api/v1/runs/anomalies", params={"range": "all"})
    assert resp.status_code == 200
    out = resp.json()

    kinds = {a["kind"] for a in out}
    assert "error_rate" in kinds
    assert "fabrication" in kinds
    assert out[0]["severity"] == "red"  # sorted severity-first
    assert all({"severity", "kind", "spawn_name", "title", "detail"} <= set(a) for a in out)


async def test_anomalies_empty_when_healthy(client):
    async with client.db_maker() as db:
        for i in range(3):
            db.add(Run(
                conversation_id="c", spawn_id=2, spawn_name="Good",
                user_message=f"good {i}", status="scored", task_tokens=50,
                total_ms=200 + i * 10, overall_score=9.0, overall_badge="good",
                error_kind=None,
            ))
        await db.commit()

    resp = await client.get("/api/v1/runs/anomalies", params={"range": "all"})
    assert resp.status_code == 200
    assert resp.json() == []
