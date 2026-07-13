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
    # E9-b: thin corpus (3 real) → the estimate PROJECTS the synthetic holdout top-up the real
    # run would mint (up to MIN_HOLDOUT_N), without minting — so the previewed pair count reaches
    # the floor rather than staying at 3.
    assert body["pairs"] >= 10
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


async def test_proposal_detail_carries_full_evidence_and_base(client):
    """GET /evolution/proposals/{id} returns the card payload: candidate_prompt, the honest
    (current) base_prompt, is_stale, and the full holdout evidence with pairs + BOTH deltas."""
    sid = await _seed_spawn(client)
    async with client.db_maker() as db:
        spawn = await db.get(Spawn, sid)
        # base_prompt_sha matches the current prompt → not stale. skill_doc canonicalizes the
        # headerless prompt "P" to a "## Instructions" section, so hash that canonical form.
        from server.services import skill_doc
        import hashlib
        base = skill_doc.apply_edits(spawn.system_prompt or "", [])
        sha = hashlib.sha256(base.encode("utf-8")).hexdigest()
        db.add(EvolutionProposal(
            spawn_id=sid, candidate_prompt="CANDIDATE PROMPT", gate_passed=True, status="open",
            base_prompt_sha=sha,
            evidence={
                "passed": True, "reason": "pass", "flags": [],
                "real_delta": {"wins": 7, "losses": 2, "ties": 1, "n": 9,
                               "win_rate": 0.7777, "p_value": 0.04, "ci95": [0.4, 0.95]},
                "synthetic_delta": {"wins": 6, "losses": 1, "ties": 0, "n": 7,
                                    "win_rate": 0.857, "p_value": 0.06, "ci95": [0.42, 0.99]},
                "evidence_tier": "strong",
                "pairs": [{"task_hash": "abc", "corpus_label": "real", "source_ref": 3,
                           "split_side": "holdout", "baseline_run_id": 101,
                           "candidate_run_id": 102, "base_out_len": 100, "cand_out_len": 120,
                           "per_dim": {"fabrication": "b", "identity": "tie", "completion": "b"},
                           "overall": "b", "position_sensitive": False}],
                "excluded_count": 4,
            },
        ))
        await db.commit()

    rows = (await client.get("/api/v1/evolution/proposals?status=open")).json()
    pid = rows[0]["id"]
    r = await client.get(f"/api/v1/evolution/proposals/{pid}")
    assert r.status_code == 200
    body = r.json()
    assert body["candidate_prompt"] == "CANDIDATE PROMPT"
    assert body["base_prompt"] and "P" in body["base_prompt"]
    assert body["is_stale"] is False
    assert body["evidence"]["real_delta"]["win_rate"] == 0.7777
    assert body["evidence"]["synthetic_delta"]["n"] == 7
    assert body["evidence"]["excluded_count"] == 4
    assert len(body["evidence"]["pairs"]) == 1
    assert body["evidence"]["pairs"][0]["candidate_run_id"] == 102
    # Deltas are NEVER merged: no combined win-rate key anywhere in the payload.
    assert "combined_delta" not in body["evidence"]
    assert "merged_delta" not in body["evidence"]


async def test_proposal_detail_marks_stale_when_base_drifted(client):
    sid = await _seed_spawn(client)
    async with client.db_maker() as db:
        db.add(EvolutionProposal(
            spawn_id=sid, candidate_prompt="C", gate_passed=True, status="open",
            base_prompt_sha="deadbeef" * 8,  # will not match the current prompt
            evidence={"real_delta": {"n": 0}, "synthetic_delta": {"n": 0}},
        ))
        await db.commit()
    rows = (await client.get("/api/v1/evolution/proposals")).json()
    pid = rows[0]["id"]
    body = (await client.get(f"/api/v1/evolution/proposals/{pid}")).json()
    assert body["is_stale"] is True


async def test_rollback_restores_prior_prompt(client):
    """POST /evolution/proposals/{id}/rollback reverts a promoted proposal: the spawn's
    system_prompt is restored from prompt_history[-1], generation_level drops back, the history
    entry is popped, and the proposal re-opens."""
    async with client.db_maker() as db:
        s = Spawn(name="RB", domain_category="x", system_prompt="NEW_GEN2_PROMPT",
                  generation_level=2,
                  config={"prompt_history": [{"old_prompt": "ORIGINAL_GEN1_PROMPT",
                                              "generation_level": 1,
                                              "promoted_at": datetime.utcnow().isoformat()}]})
        db.add(s)
        await db.commit()
        await db.refresh(s)
        sid = s.id
        prop = EvolutionProposal(spawn_id=sid, candidate_prompt="NEW_GEN2_PROMPT",
                                 gate_passed=True, status="promoted",
                                 promoted_at=datetime.utcnow(), evidence={})
        db.add(prop)
        await db.commit()
        await db.refresh(prop)
        pid = prop.id

    r = await client.post(f"/api/v1/evolution/proposals/{pid}/rollback")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["generation_level"] == 1

    async with client.db_maker() as db:
        s = await db.get(Spawn, sid)
        assert s.system_prompt == "ORIGINAL_GEN1_PROMPT"
        assert s.generation_level == 1
        assert list((s.config or {}).get("prompt_history", [])) == []
        prop = await db.get(EvolutionProposal, pid)
        assert prop.status == "open"
        assert prop.promoted_at is None

    # A ConversationEvent(kind='evolution') was logged for the rollback.
    from server.db.models import ConversationEvent
    from sqlalchemy import select as _select
    async with client.db_maker() as db:
        evs = (await db.execute(
            _select(ConversationEvent).where(ConversationEvent.kind == "evolution"))
        ).scalars().all()
        assert any((e.ref or {}).get("action") == "rollback" for e in evs)


async def test_rollback_refuses_non_promoted(client):
    sid = await _seed_spawn(client)
    async with client.db_maker() as db:
        db.add(EvolutionProposal(spawn_id=sid, candidate_prompt="C", gate_passed=True,
                                 status="open", evidence={}))
        await db.commit()
    rows = (await client.get("/api/v1/evolution/proposals")).json()
    pid = rows[0]["id"]
    r = await client.post(f"/api/v1/evolution/proposals/{pid}/rollback")
    assert r.status_code == 409


async def test_reject_marks_rejected(client):
    sid = await _seed_spawn(client)
    async with client.db_maker() as db:
        db.add(EvolutionProposal(spawn_id=sid, candidate_prompt="C", gate_passed=True,
                                 status="open", evidence={}))
        await db.commit()
    rows = (await client.get("/api/v1/evolution/proposals")).json()
    pid = rows[0]["id"]
    r = await client.post(f"/api/v1/evolution/proposals/{pid}/reject")
    assert r.status_code == 200 and r.json()["ok"] is True
    async with client.db_maker() as db:
        prop = await db.get(EvolutionProposal, pid)
        assert prop.status == "rejected"
