"""Orchestrates the offline evolution loop: propose an improvement, and (on human
confirm) promote it. Self-manages DB sessions like run_eval_service.
"""
from __future__ import annotations

import logging
from datetime import datetime

from arslan.core.param_registry import DEFAULT_REGISTRY
from server.db import session as db_session
from server.db.models import EvolutionProposal, Spawn
from server.services import evaluator, optimizer, replay_set

logger = logging.getLogger(__name__)


def _persona(spawn: Spawn) -> str:
    return (f"role: {spawn.persona_role or ''}\ntone: {spawn.persona_tone or ''}\n"
            f"{spawn.system_prompt or ''}")


async def propose_improvement(spawn_id: int, *, cap: int = 5) -> dict:
    """Build a replay set, draft a candidate prompt, evaluate+gate it, persist the
    proposal. Returns {proposal_id, candidate_prompt, gate, evidence}."""
    items = await replay_set.build(spawn_id, cap=cap)
    if not items:
        return {"proposal_id": None, "candidate_prompt": None,
                "gate": {"passed": False, "reason": "no scored runs", "aggregate": None},
                "evidence": None}

    async with db_session.AsyncSessionLocal() as db:
        spawn = await db.get(Spawn, spawn_id)
    if spawn is None:
        return {"proposal_id": None, "candidate_prompt": None,
                "gate": {"passed": False, "reason": "spawn not found", "aggregate": None},
                "evidence": None}

    candidate = await optimizer.propose(spawn, items)
    result = await evaluator.evaluate(
        spawn_id=spawn_id, persona=_persona(spawn),
        candidate_prompt=candidate, replay_items=items,
    )
    gate = result["gate"]

    async with db_session.AsyncSessionLocal() as db:
        prop = EvolutionProposal(
            spawn_id=spawn_id, candidate_prompt=candidate,
            gate_passed=bool(gate["passed"]), evidence=result, status="proposed",
        )
        db.add(prop)
        await db.commit()
        await db.refresh(prop)
        proposal_id = prop.id

    return {"proposal_id": proposal_id, "candidate_prompt": candidate,
            "gate": gate, "evidence": result}


async def confirm_proposal(proposal_id: int) -> dict:
    """Promote a proposed candidate iff its gate passed. Stores the old prompt in
    spawn.config['prompt_history'] for rollback, bumps generation_level."""
    async with db_session.AsyncSessionLocal() as db:
        prop = await db.get(EvolutionProposal, proposal_id)
        if prop is None:
            return {"ok": False, "reason": "proposal not found"}
        if prop.status != "proposed":
            return {"ok": False, "reason": f"already {prop.status}"}
        if not prop.gate_passed:
            return {"ok": False, "reason": "gate not passed; refusing to promote"}
        spawn = await db.get(Spawn, prop.spawn_id)
        if spawn is None:
            return {"ok": False, "reason": "spawn not found"}

        now = datetime.utcnow()
        cfg = dict(spawn.config or {})
        history = list(cfg.get("prompt_history", []))
        history.append({
            "old_prompt": DEFAULT_REGISTRY.get("system_prompt", spawn),
            "generation_level": spawn.generation_level,
            "promoted_at": now.isoformat(),
        })
        cfg["prompt_history"] = history
        spawn.config = cfg
        DEFAULT_REGISTRY.set("system_prompt", spawn, prop.candidate_prompt)
        spawn.generation_level = (spawn.generation_level or 1) + 1
        prop.status = "promoted"
        prop.promoted_at = now
        await db.commit()
        gen = spawn.generation_level

    return {"ok": True, "spawn_id": prop.spawn_id, "generation_level": gen}
