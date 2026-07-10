"""S2 E5 evolution API: estimate, 202 enqueue, proposal inbox, stale-confirm 409."""
from __future__ import annotations

from datetime import datetime

from server.db.models import EvolutionProposal, Run, Spawn
from server.services import evolution_loop, evolution_watcher


async def _seed_spawn(client, name="S") -> int:
    async with client.db_maker() as db:
        s = Spawn(name=name, domain_category="x", system_prompt="P", generation_level=1, config={})
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


async def test_estimate_endpoint_shape(client):
    sid = await _seed_spawn(client)
    async with client.db_maker() as db:
        for i in range(3):
            db.add(Run(conversation_id="c", spawn_id=sid, user_message=f"task-{i}",
                       task_tokens=120, status="scored", kind="live", epoch=1,
                       started_at=datetime.utcnow()))
        await db.commit()

    r = await client.get(f"/api/v1/spawns/{sid}/evolve/estimate")
    assert r.status_code == 200
    body = r.json()
    for key in ("pairs", "dispatches", "judge_calls", "optimizer_calls",
                "synth_calls", "est_tokens", "lower_bound"):
        assert key in body
    assert body["lower_bound"] is True
    assert body["pairs"] == 3
    assert body["est_tokens"] > 0


async def test_evolve_returns_202_and_does_not_block(client, monkeypatch):
    sid = await _seed_spawn(client)
    blocked = {"propose": False}

    async def fake_enqueue(spawn_id, *, manual=False):
        assert manual is True
        return 55

    async def fake_propose(spawn_id, **k):
        blocked["propose"] = True
        return {"proposal_id": 1, "candidate_prompt": "C", "gate": {}, "evidence": {}}

    monkeypatch.setattr(evolution_watcher, "enqueue_attempt", fake_enqueue)
    monkeypatch.setattr(evolution_loop, "propose_improvement", fake_propose)

    r = await client.post(f"/api/v1/spawns/{sid}/evolve")
    assert r.status_code == 202
    assert r.json()["attempt_id"] == 55
    assert blocked["propose"] is False   # the loop was NOT run inline


async def test_list_proposals_inbox(client):
    sid = await _seed_spawn(client)
    async with client.db_maker() as db:
        db.add(EvolutionProposal(
            spawn_id=sid, candidate_prompt="C", gate_passed=True, status="open",
            base_prompt_sha="a" * 64,
            evidence={"real_delta": {"win_rate": 0.7, "n": 10}, "synthetic_delta": {"n": 0},
                      "evidence_tier": "medium", "flags": ["synthetic_driven"]},
        ))
        db.add(EvolutionProposal(spawn_id=sid, candidate_prompt="C2", gate_passed=False,
                                 status="promoted", evidence={}))
        await db.commit()

    r = await client.get("/api/v1/evolution/proposals?status=open")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "open" and row["gate_passed"] is True
    assert row["real_delta"]["win_rate"] == 0.7
    assert row["evidence_tier"] == "medium"
    assert "synthetic_driven" in row["flags"]

    # No filter → both proposals.
    r_all = await client.get("/api/v1/evolution/proposals")
    assert len(r_all.json()) == 2


async def test_confirm_stale_returns_409(client, monkeypatch):
    async def fake_confirm(proposal_id):
        return {"ok": False, "reason": "already stale"}

    monkeypatch.setattr(evolution_loop, "confirm_proposal", fake_confirm)
    r = await client.post("/api/v1/evolution/proposals/7/confirm")
    assert r.status_code == 409
