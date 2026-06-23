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
