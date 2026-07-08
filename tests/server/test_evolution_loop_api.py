"""Tests for POST /api/v1/spawns/{id}/evolve and /api/v1/evolution/proposals/{id}/confirm."""
from __future__ import annotations


from server.db.models import Spawn
from server.services import evolution_loop


async def test_evolve_endpoint_returns_proposal(client, monkeypatch):
    async with client.db_maker() as db:
        s = Spawn(name="S", domain_category="x", system_prompt="P", generation_level=1, config={})
        db.add(s)
        await db.commit()
        await db.refresh(s)
        sid = s.id

    async def fake_propose(spawn_id, *, cap=5):
        return {
            "proposal_id": 42,
            "candidate_prompt": "C",
            "gate": {"passed": True, "reason": "ok", "aggregate": {}},
            "evidence": {},
        }

    monkeypatch.setattr(evolution_loop, "propose_improvement", fake_propose)

    r = await client.post(f"/api/v1/spawns/{sid}/evolve")
    assert r.status_code == 200
    assert r.json()["proposal_id"] == 42
    assert r.json()["gate"]["passed"] is True


async def test_confirm_endpoint(client, monkeypatch):
    async def fake_confirm(proposal_id):
        return {"ok": True, "spawn_id": 1, "generation_level": 2}

    monkeypatch.setattr(evolution_loop, "confirm_proposal", fake_confirm)

    r = await client.post("/api/v1/evolution/proposals/42/confirm")
    assert r.status_code == 200
    assert r.json()["ok"] is True and r.json()["generation_level"] == 2
