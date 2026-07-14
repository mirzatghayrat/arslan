"""Orchestrates the offline evolution loop: propose an improvement, and (on human
confirm) promote it. Self-manages DB sessions like run_eval_service.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from arslan.core.param_registry import DEFAULT_REGISTRY
from server.db import session as db_session
from server.db.models import ConversationEvent, EvolutionProposal, Spawn
from server.services import evaluator, optimizer, replay_gate, replay_set, skill_doc

logger = logging.getLogger(__name__)


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _persona(spawn: Spawn) -> str:
    return (f"role: {spawn.persona_role or ''}\ntone: {spawn.persona_tone or ''}\n"
            f"{spawn.system_prompt or ''}")


async def _val_outputs(spawn_id: int, doc: str, val: list[dict]) -> dict:
    """Run `doc` over val hermetically, return {run_id: output} for the running-best
    baseline. Byte-identical ambient across the val split (one snapshot)."""
    from server.db import session as db_session
    from server.services import replay_run
    out = {}
    async with db_session.AsyncSessionLocal() as db:
        ambient = await replay_run.snapshot_ambient(
            db, spawn_id=spawn_id, conversation_id=replay_run.REPLAY_CONVERSATION_ID)
        for it in val:
            arm = await replay_run.run_arm(
                db, spawn_id=spawn_id, task=it["task"], system_prompt=doc, ambient=ambient)
            out[it["run_id"]] = arm["output"]
    return out


def _optimizer_item(pt: dict, by_run: dict) -> dict:
    """Turn ONE propose-side corpus pairtask into the replay-item shape the optimizer /
    evaluator / _val_outputs consume ({run_id, task, baseline_output, baseline_overall,
    baseline_dims}). A real pairtask joins its stored judge evidence from `by_run`
    (keyed by run id); a synthetic one has no baseline eval, so it carries an empty
    evidence body under a stable synthetic key. `run_id` is only ever used as a dict key
    for the running-best baseline map, so any stable hashable value is fine."""
    if pt.get("corpus_label") == "real":
        rid = pt.get("source_ref")
        rich = by_run.get(rid, {})
        return {"run_id": rid, "task": pt["task"],
                "baseline_output": rich.get("baseline_output", ""),
                "baseline_overall": rich.get("baseline_overall"),
                "baseline_dims": rich.get("baseline_dims", {})}
    sr = pt.get("source_ref") or {}
    key = f"synth:{sr.get('synth_id')}:{sr.get('version')}"
    return {"run_id": key, "task": pt["task"], "baseline_output": "",
            "baseline_overall": None, "baseline_dims": {}}


def _subsplit_propose(items: list[dict], *, train_cap: int, val_cap: int) -> tuple[list, list]:
    """Deterministic train/val split WITHIN the propose partition only (every 3rd → val).
    Holdout tasks are excluded upstream and NEVER reach here — this split touches propose
    tasks exclusively, so the optimizer can never train or score on a certifying task."""
    train, val = [], []
    for idx, it in enumerate(items):
        (val if idx % 3 == 2 else train).append(it)
    return train[:train_cap], val[:val_cap]


async def propose_improvement(spawn_id: int, *, epochs: int = 3, lr_budget: int = 2,
                              train_cap: int = 12, val_cap: int = 8) -> dict:
    """Multi-epoch bounded-edit loop. Each epoch: snapshot the running-best outputs on the
    PROPOSE-side val, ask the optimizer for <=lr_budget bounded edits (excluding rejected
    ones), and accept any edit that beats the running best. Rejected edits buffer into
    later epochs; converge when an epoch accepts nothing. A final guard requires the
    accumulated doc to beat the ORIGINAL before a proposal is persisted.
    Returns {proposal_id, candidate_prompt, gate, evidence}.

    HOLDOUT ISOLATION (spec §E4 / §2 ruling 3 — the methodology invariant): the corpus is
    built ONCE and split by ReplayGate's own (spawn_id, task) hash. The optimizer's
    train/val come EXCLUSIVELY from the PROPOSE side; the certifying gate at the end runs
    over the SAME corpus and computes every user-facing win-rate on the HOLDOUT side only.
    Because it is one corpus, the tasks that certify the proposal are provably disjoint from
    the tasks the optimizer ever saw — no candidate is tuned on a task that then certifies it.

    Cost ≈ epochs × (val running-best dispatches + accepted-candidates × val eval
    dispatches) + one final paired gate over the corpus; the API caller uses all defaults."""
    async with db_session.AsyncSessionLocal() as db:
        spawn = await db.get(Spawn, spawn_id)
        if spawn is None:
            return {"proposal_id": None, "candidate_prompt": None,
                    "gate": {"passed": False, "reason": "spawn not found", "aggregate": None},
                    "evidence": None}
        # baseline_started_at defaults to None → build_corpus reads the declared clean-corpus
        # start from settings (E9); the SAME corpus is reused for the final gate below.
        # mint=True (E9-b): the REAL gate path tops a thin holdout up to the floor so the gate is
        # reachable — the read-only cost preview (evolution_estimate) never does this.
        corpus = await replay_gate.build_corpus(db, spawn_id, baseline_started_at=None, mint=True)

    # Rich baseline judge evidence for the optimizer's edit digest (keyed by run id).
    rich = await replay_set.build(spawn_id, cap=train_cap + val_cap)
    by_run = {r["run_id"]: r for r in rich}

    # The optimizer sees the PROPOSE partition ONLY — holdout tasks are filtered out here
    # and never enter the loop (the isolation invariant, enforced structurally).
    propose_items = [_optimizer_item(pt, by_run)
                     for pt in corpus if pt.get("split_side") == "propose"]
    train, val = _subsplit_propose(propose_items, train_cap=train_cap, val_cap=val_cap)
    if not val:
        return {"proposal_id": None, "candidate_prompt": None,
                "gate": {"passed": False, "reason": "insufficient scored runs", "aggregate": None},
                "evidence": None}

    # `spawn` is detached after the session closes above; below we only read eagerly-loaded
    # columns (system_prompt / persona_role / persona_tone / name) — never a lazy relationship.
    # Canonicalize the doc to its sectioned form up front (a headerless prompt becomes one
    # `## Instructions` section) so the no-op-edit guard below (`cand_doc == doc`) fires even
    # on the common headerless-prompt case.
    original = skill_doc.apply_edits(spawn.system_prompt or "", [])
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
                running_best = await _val_outputs(spawn_id, doc, val)
                last_best_doc = doc
            candidates = await optimizer.propose_edits(
                spawn, train, lr_budget=lr_budget, avoid=rejected)
        except Exception as exc:  # noqa: BLE001
            # I1: finalize accumulated work, don't crash — BUT only once there IS work. A failure
            # with NO accepted edit yet is an infra/adapter failure that produced nothing (E9-b
            # dead-adapter bug): re-raise so _perform_attempt records outcome='error' with the real
            # reason, instead of masking it as a ~0-second "no accepted edit beats the original"
            # quality verdict that also inflates the quality backoff.
            if not accepted:
                raise
            logger.warning("evolution epoch aborted after %d accepted edit(s), finalizing early: %s",
                           len(accepted), exc)
            break
        if not candidates:
            break  # optimizer is out of ideas (converged / plateau)
        for edit in candidates:
            cand_doc = skill_doc.apply_edits(doc, [edit])
            if cand_doc == doc:                            # M2: no-op edit -> auto-reject, no dispatch
                rejected.append(edit)
                continue
            if len(cand_doc) > replay_gate._length_ceiling(original) or \
                    len(cand_doc) > replay_gate.MAX_PROMPT_LEN:
                rejected.append(edit)                      # E9-b: would blow the holdout length
                continue                                   # cap — reject WITHOUT judging (bounded
                                                           # by construction, saves judge cost)
            try:
                res = await evaluator.evaluate(
                    spawn_id=spawn_id, persona=persona, candidate_prompt=cand_doc,
                    replay_items=val, baseline_outputs=running_best)
            except Exception as exc:  # noqa: BLE001
                logger.warning("evolution candidate eval failed, skipping: %s", exc)
                continue
            if res["gate"]["passed"]:
                doc = cand_doc
                accepted.append(edit)
                per_epoch.append({"edit": edit, "verdict": res["gate"]})
            else:
                rejected.append(edit)

    # The optimizer loop above is only the CANDIDATE GENERATOR, scored on the PROPOSE split.
    # The real PASS decision is the paired ReplayGate on the HOLDOUT split — real+synthetic,
    # position-swapped, per-dim + real-floor. No accepted edit at all → nothing to gate.
    if not accepted or doc == original:
        return {"proposal_id": None, "candidate_prompt": doc,
                "gate": {"passed": False, "reason": "no accepted edit beats the original",
                         "aggregate": None},
                "evidence": {"diff": accepted, "per_epoch": per_epoch}}

    # Certify on the SAME corpus we split above: the gate restricts every user-facing delta
    # to the holdout side (disjoint from the optimizer's propose tasks by construction).
    try:
        async with db_session.AsyncSessionLocal() as db:
            gate = await replay_gate.run_gate(
                db, spawn_id=spawn_id, candidate_prompt=doc, baseline_prompt=original,
                corpus=corpus, persona=persona)
    except Exception as exc:  # noqa: BLE001  -- I1: degrade to no-op, keep accumulated evidence
        logger.warning("evolution ReplayGate failed: %s", exc)
        return {"proposal_id": None, "candidate_prompt": doc,
                "gate": {"passed": False, "reason": f"gate failed: {exc}", "aggregate": None},
                "evidence": {"diff": accepted, "per_epoch": per_epoch}}

    uf = gate.user_facing()
    # The propose-side aggregate the optimizer iterated against — a NON-user-facing
    # diagnostic (never a rendered win-rate) kept alongside the diff for auditing.
    internal = gate.internal_signal()
    if not gate.passed:
        return {"proposal_id": None, "candidate_prompt": doc,
                "gate": {"passed": False, "reason": gate.reason, "aggregate": uf},
                "evidence": {"diff": accepted, "per_epoch": per_epoch, "gate": uf,
                             "internal_signal": internal}}

    # PASS. Persist a LIVING proposal (status='open', spec §E4) whose evidence is the
    # holdout-only GateResult — including protected_run_ids so E2's redact sweep exempts
    # the two arms' replay Runs. base_prompt_sha pins the baseline the gate ran against.
    async with db_session.AsyncSessionLocal() as db:
        prop = EvolutionProposal(spawn_id=spawn_id, candidate_prompt=doc, gate_passed=True,
                                 evidence=uf, status="open", base_prompt_sha=_sha(original))
        db.add(prop)
        await db.commit()
        await db.refresh(prop)
        proposal_id = prop.id

    return {"proposal_id": proposal_id, "candidate_prompt": doc,
            "gate": {"passed": True, "reason": gate.reason, "aggregate": uf},
            "evidence": {"diff": accepted, "per_epoch": per_epoch, "gate": uf,
                         "internal_signal": internal}}


REFRESH_MIN_NEW_TASKS = 5


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


async def refresh_proposal(db, proposal_id: int) -> dict:
    """Keep a living proposal honest (spec §E4 decision B.2). For a status='open' proposal:

      1. If the spawn's CURRENT prompt drifted from `base_prompt_sha` → mark it 'stale' (the
         gate ran against a prompt that no longer exists; a human re-runs it).
      2. Else, once >=REFRESH_MIN_NEW_TASKS new replayable REAL tasks have arrived since the
         last refresh, replay the NEW real pairs, ACCUMULATE them with the proposal's stored
         holdout pairs, and recompute the verdict/deltas/tier over the union. If the
         accumulated evidence now drops below threshold, flip `gate_passed=False` and flag
         `no_longer_passing` — but the status stays 'open' (the human decides去留).

    `db` is the caller's session (endpoint or watcher). Synthetic tasks are already captured
    in the stored pairs, so only NEW real pairs are replayed — no double counting."""
    prop = await db.get(EvolutionProposal, proposal_id)
    if prop is None:
        return {"ok": False, "reason": "proposal not found"}
    if prop.status != "open":
        return {"ok": False, "reason": f"not open (status={prop.status})", "status": prop.status}
    spawn = await db.get(Spawn, prop.spawn_id)
    if spawn is None:
        return {"ok": False, "reason": "spawn not found"}

    original = skill_doc.apply_edits(spawn.system_prompt or "", [])
    if prop.base_prompt_sha and _sha(original) != prop.base_prompt_sha:
        prop.status = "stale"
        await db.commit()
        return {"ok": True, "status": "stale", "refreshed": False,
                "reason": "base prompt drifted", "proposal_id": proposal_id}

    ev = dict(prop.evidence or {})
    since = _parse_dt(ev.get("last_refreshed_at")) or prop.created_at
    corpus = await replay_gate.build_corpus(db, prop.spawn_id, baseline_started_at=since)
    new_real = [c for c in corpus if c.get("corpus_label") == "real"]
    if len(new_real) < REFRESH_MIN_NEW_TASKS:
        return {"ok": True, "status": prop.status, "refreshed": False,
                "reason": "insufficient_new_tasks", "new_tasks": len(new_real),
                "proposal_id": proposal_id}

    persona = _persona(spawn)
    gate = await replay_gate.run_gate(
        db, spawn_id=prop.spawn_id, candidate_prompt=prop.candidate_prompt,
        baseline_prompt=original, corpus=new_real, persona=persona)

    accumulated = list(ev.get("pairs", [])) + list(gate.pairs)
    verdict = replay_gate.recompute_verdict(accumulated)

    # Optional-stopping honesty (spec §4): a living proposal is re-evaluated over accumulating
    # holdout evidence with NO multiple-comparison correction, so a "significant" tier here is
    # a repeated-looks snapshot, not a controlled end-of-experiment test. Count the refreshes
    # and flag the proposal so the card states the tier is uncorrected for sequential looks.
    refresh_count = int(ev.get("refresh_count", 0)) + 1
    flags = list(verdict.get("flags", []))
    if not verdict["passed"] and "no_longer_passing" not in flags:
        flags.append("no_longer_passing")
    if refresh_count >= 1 and "sequential_uncorrected" not in flags:
        flags.append("sequential_uncorrected")

    ev.update({
        "pairs": accumulated,
        "real_delta": verdict["real_delta"],
        "synthetic_delta": verdict["synthetic_delta"],
        "evidence_tier": verdict["evidence_tier"],
        "passed": verdict["passed"],
        "reason": verdict["reason"],
        "flags": flags,
        "refresh_count": refresh_count,
        "last_refreshed_at": datetime.utcnow().isoformat(),
    })
    prop.evidence = ev
    prop.gate_passed = bool(verdict["passed"])
    # status STAYS 'open' — a no-longer-passing living proposal is surfaced, not auto-killed.
    await db.commit()
    return {"ok": True, "status": prop.status, "refreshed": True,
            "gate_passed": prop.gate_passed, "flags": flags,
            "reason": verdict["reason"], "proposal_id": proposal_id}


async def confirm_proposal(proposal_id: int) -> dict:
    """Promote a proposed candidate iff its gate passed. Stores the old prompt in
    spawn.config['prompt_history'] for rollback, bumps generation_level.

    Accepts both the legacy 'proposed' status and the S2 living-proposal 'open' status;
    any other status (promoted/rejected/stale) refuses."""
    async with db_session.AsyncSessionLocal() as db:
        prop = await db.get(EvolutionProposal, proposal_id)
        if prop is None:
            return {"ok": False, "reason": "proposal not found"}
        if prop.status not in ("proposed", "open"):
            return {"ok": False, "reason": f"already {prop.status}"}
        if not prop.gate_passed:
            return {"ok": False, "reason": "gate not passed; refusing to promote"}
        spawn = await db.get(Spawn, prop.spawn_id)
        if spawn is None:
            return {"ok": False, "reason": "spawn not found"}

        # Staleness re-check at confirm time (spec §E7 audit #14). The gate ran against the
        # prompt whose sha is base_prompt_sha; if the spawn's CURRENT prompt has drifted
        # since (e.g. another proposal for this spawn was promoted first), promoting this one
        # would silently overwrite that change against a baseline that no longer exists. Use
        # the SAME canonicalization propose_improvement used to compute base_prompt_sha.
        original = skill_doc.apply_edits(spawn.system_prompt or "", [])
        if prop.base_prompt_sha and _sha(original) != prop.base_prompt_sha:
            prop.status = "stale"
            await db.commit()
            return {"ok": False, "status": "stale",
                    "reason": "base prompt drifted; proposal marked stale — re-run the gate"}

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


async def rollback_proposal(db, proposal_id: int) -> dict:
    """Undo a promotion (spec §E7 audit #14). Restores the spawn to the previous generation:
    pop spawn.config['prompt_history'][-1] and write its `old_prompt` back onto the spawn, reset
    generation_level to that entry's, and re-open the proposal (status='open', promoted_at
    cleared) so it becomes a living candidate again rather than a dead promotion. Logs an
    evolution ConversationEvent. Refuses anything not currently 'promoted', or a promotion with
    no recorded prompt_history to restore from. `db` is the caller's session (endpoint)."""
    prop = await db.get(EvolutionProposal, proposal_id)
    if prop is None:
        return {"ok": False, "reason": "proposal not found"}
    if prop.status != "promoted":
        return {"ok": False, "reason": f"not promoted (status={prop.status})"}
    spawn = await db.get(Spawn, prop.spawn_id)
    if spawn is None:
        return {"ok": False, "reason": "spawn not found"}

    cfg = dict(spawn.config or {})
    history = list(cfg.get("prompt_history", []))
    if not history:
        return {"ok": False, "reason": "no prompt history to roll back to"}
    prev = history.pop()
    DEFAULT_REGISTRY.set("system_prompt", spawn, prev.get("old_prompt", spawn.system_prompt))
    spawn.generation_level = prev.get("generation_level", max((spawn.generation_level or 2) - 1, 1))
    cfg["prompt_history"] = history
    spawn.config = cfg
    prop.status = "open"
    prop.promoted_at = None

    db.add(ConversationEvent(
        conversation_id=f"spawn-{prop.spawn_id}", kind="evolution",
        ref={"action": "rollback", "proposal_id": proposal_id,
             "to_generation": spawn.generation_level},
        summary=f"回滚进化提案 #{proposal_id} → 第 {spawn.generation_level} 代",
    ))
    await db.commit()
    return {"ok": True, "spawn_id": prop.spawn_id, "generation_level": spawn.generation_level}


async def reject_proposal(db, proposal_id: int) -> dict:
    """Mark a proposal 'rejected' (human dismiss from the inbox). Refuses a proposal that was
    already promoted — a promoted candidate must be rolled back, not rejected. `db` is the
    caller's session (endpoint)."""
    prop = await db.get(EvolutionProposal, proposal_id)
    if prop is None:
        return {"ok": False, "reason": "proposal not found"}
    if prop.status == "promoted":
        return {"ok": False, "reason": "already promoted; roll back instead"}
    prop.status = "rejected"
    await db.commit()
    return {"ok": True, "spawn_id": prop.spawn_id}
