"""tests/server/test_run_cancel_api.py — POST /runs/{id}/cancel (S3-M1).

202 cancels a registered live task; 404 unknown run; 409 terminal run.
"""
from __future__ import annotations

import asyncio

import pytest

from server.db.models import Run
from server.services import run_registry


@pytest.fixture(autouse=True)
def _clean_registry():
    """Registry is process-global — clear around each test to avoid leakage."""
    run_registry._tasks.clear()
    run_registry._by_conversation.clear()
    yield
    run_registry._tasks.clear()
    run_registry._by_conversation.clear()


async def test_cancel_endpoint_cancels_live_run(client):
    async def _work():
        await asyncio.sleep(30)

    task = asyncio.create_task(_work())
    run_registry.register(4242, "conv-x", task)
    try:
        resp = await client.post("/api/v1/runs/4242/cancel")
        assert resp.status_code == 202
        assert resp.json() == {"ok": True}
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        run_registry.unregister(4242, "conv-x")


async def test_cancel_unknown_run_404s(client):
    resp = await client.post("/api/v1/runs/999999/cancel")
    assert resp.status_code == 404


async def test_cancel_finished_run_409s(client):
    """A terminal run (status='scored') is not in the registry and not cancellable."""
    async with client.db_maker() as db:
        run = Run(conversation_id="c1", spawn_name="Mermer", user_message="x",
                  status="scored", task_tokens=0, total_ms=100,
                  overall_score=8.0, overall_badge="good")
        db.add(run)
        await db.commit()
        await db.refresh(run)
        run_id = run.id

    resp = await client.post(f"/api/v1/runs/{run_id}/cancel")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "not cancellable" in detail
    assert "scored" in detail
