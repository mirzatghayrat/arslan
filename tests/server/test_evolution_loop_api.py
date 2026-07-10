"""Tests for POST /api/v1/spawns/{id}/evolve and /api/v1/evolution/proposals/{id}/confirm."""
from __future__ import annotations


from server.db.models import Spawn
from server.services import evolution_loop, evolution_watcher


async def test_evolve_endpoint_enqueues_202(client, monkeypatch):
    # E5: /evolve is now a BACKGROUND job — 202 + attempt_id, it does NOT run the loop inline.
    async with client.db_maker() as db:
        s = Spawn(name="S", domain_category="x", system_prompt="P", generation_level=1, config={})
        db.add(s)
        await db.commit()
        await db.refresh(s)
        sid = s.id

    called = {"propose": False}

    async def fake_enqueue(spawn_id, *, manual=False):
        assert manual is True
        return 77

    async def fake_propose(spawn_id, **k):  # must NOT be awaited inline by the endpoint
        called["propose"] = True
        return {"proposal_id": 1, "candidate_prompt": "C", "gate": {}, "evidence": {}}

    monkeypatch.setattr(evolution_watcher, "enqueue_attempt", fake_enqueue)
    monkeypatch.setattr(evolution_loop, "propose_improvement", fake_propose)

    r = await client.post(f"/api/v1/spawns/{sid}/evolve")
    assert r.status_code == 202
    assert r.json()["attempt_id"] == 77
    assert called["propose"] is False  # the endpoint returned without blocking on the loop


async def test_confirm_endpoint(client, monkeypatch):
    async def fake_confirm(proposal_id):
        return {"ok": True, "spawn_id": 1, "generation_level": 2}

    monkeypatch.setattr(evolution_loop, "confirm_proposal", fake_confirm)

    r = await client.post("/api/v1/evolution/proposals/42/confirm")
    assert r.status_code == 200
    assert r.json()["ok"] is True and r.json()["generation_level"] == 2
