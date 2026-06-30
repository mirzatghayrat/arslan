"""Orchestrates the offline evolution loop: propose an improvement, and (on human
confirm) promote it. Self-manages DB sessions like run_eval_service.
"""
from __future__ import annotations

import logging
from datetime import datetime

from arslan.core.param_registry import DEFAULT_REGISTRY
from server.db import session as db_session
from server.db.models import EvolutionProposal, Spawn
from server.orchestrator import dispatcher
from server.services import evaluator, optimizer, replay_set, skill_doc

logger = logging.getLogger(__name__)


def _persona(spawn: Spawn) -> str:
    return (f"role: {spawn.persona_role or ''}\ntone: {spawn.persona_tone or ''}\n"
            f"{spawn.system_prompt or ''}")


async def _val_outputs(spawn_id: int, doc: str, val: list[dict]) -> dict:
    """Run `doc` over val, return {run_id: output} for the running-best baseline."""
    out = {}
    for it in val:
        gen = await dispatcher.dispatch("evolution-eval", spawn_id=spawn_id,
                                        task_brief=it["task"], system_prompt_override=doc,
                                        persist=False)
        out[it["run_id"]] = gen.get("full_output", "")
    return out


async def propose_improvement(spawn_id: int, *, epochs: int = 3, lr_budget: int = 2,
                              train_cap: int = 12, val_cap: int = 8) -> dict:
    """Multi-epoch bounded-edit loop. Each epoch: snapshot the running-best outputs on
    held-out val, ask the optimizer for <=lr_budget bounded edits (excluding rejected
    ones), and accept any edit that beats the running best. Rejected edits buffer into
    later epochs; converge when an epoch accepts nothing. A final guard requires the
    accumulated doc to beat the ORIGINAL on held-out val before a proposal is persisted.
    Returns {proposal_id, candidate_prompt, gate, evidence}.

    Cost ≈ epochs × (val_cap running-best dispatches + accepted-candidates × val_cap eval
    dispatches); the API caller uses all defaults."""
    split = await replay_set.build_split(spawn_id, train_cap=train_cap, val_cap=val_cap)
    if not split["val"]:
        return {"proposal_id": None, "candidate_prompt": None,
                "gate": {"passed": False, "reason": "insufficient scored runs", "aggregate": None},
                "evidence": None}

    async with db_session.AsyncSessionLocal() as db:
        spawn = await db.get(Spawn, spawn_id)
    if spawn is None:
        return {"proposal_id": None, "candidate_prompt": None,
                "gate": {"passed": False, "reason": "spawn not found", "aggregate": None},
                "evidence": None}

    original = spawn.system_prompt or ""
    doc = original
    persona = _persona(spawn)
    rejected: list[dict] = []
    accepted: list[dict] = []
    per_epoch: list[dict] = []
    last_best_doc = None
    running_best: dict = {}

    for _ in range(epochs):
        try:
            if doc != last_best_doc:                       # M1: skip recompute if doc unchanged
                running_best = await _val_outputs(spawn_id, doc, split["val"])
                last_best_doc = doc
            candidates = await optimizer.propose_edits(
                spawn, split["train"], lr_budget=lr_budget, avoid=rejected)
        except Exception as exc:  # noqa: BLE001  -- I1: finalize accumulated work, don't crash
            logger.warning("evolution epoch aborted, finalizing early: %s", exc)
            break
        if not candidates:
            break  # optimizer is out of ideas (converged / plateau)
        for edit in candidates:
            cand_doc = skill_doc.apply_edits(doc, [edit])
            if cand_doc == doc:                            # M2: no-op edit -> auto-reject, no dispatch
                rejected.append(edit)
                continue
            try:
                res = await evaluator.evaluate(
                    spawn_id=spawn_id, persona=persona, candidate_prompt=cand_doc,
                    replay_items=split["val"], baseline_outputs=running_best)
            except Exception as exc:  # noqa: BLE001
                logger.warning("evolution candidate eval failed, skipping: %s", exc)
                continue
            if res["gate"]["passed"]:
                doc = cand_doc
                accepted.append(edit)
                per_epoch.append({"edit": edit, "verdict": res["gate"]})
            else:
                rejected.append(edit)

    # final guard: must beat the ORIGINAL on held-out val
    try:
        final = await evaluator.evaluate(spawn_id=spawn_id, persona=persona, candidate_prompt=doc,
                                         replay_items=split["val"])
    except Exception as exc:  # noqa: BLE001  -- I1: degrade to no-op, keep accumulated evidence
        logger.warning("evolution final guard eval failed: %s", exc)
        return {"proposal_id": None, "candidate_prompt": doc,
                "gate": {"passed": False, "reason": f"final eval failed: {exc}", "aggregate": None},
                "evidence": {"diff": accepted, "per_epoch": per_epoch}}
    gate = final["gate"]
    if not accepted or not gate["passed"]:
        return {"proposal_id": None, "candidate_prompt": doc,
                "gate": {"passed": False, "reason": "no accepted edit beats the original",
                         "aggregate": gate["aggregate"]},
                "evidence": {"diff": accepted, "per_epoch": per_epoch, "final": final}}

    async with db_session.AsyncSessionLocal() as db:
        prop = EvolutionProposal(spawn_id=spawn_id, candidate_prompt=doc, gate_passed=True,
                                 evidence={"diff": accepted, "per_epoch": per_epoch, "final": final},
                                 status="proposed")
        db.add(prop)
        await db.commit()
        await db.refresh(prop)
        proposal_id = prop.id

    return {"proposal_id": proposal_id, "candidate_prompt": doc, "gate": gate,
            "evidence": {"diff": accepted, "per_epoch": per_epoch}}


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
