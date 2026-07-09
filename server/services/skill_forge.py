"""Skill forge: author a skill draft and, on human confirm, register it as a
real, live, equippable library skill.

Mirrors the offline-evolution SHAPE (candidate -> gate -> proposal -> human
confirm; never auto-promote). Slice 1 IS the spine: the gate is the human
confirm (promote_candidate). Slice 2 will insert a real eval gate before a
candidate reaches "proposed" — the `samples`/`evidence`/`observing`->`proposed`
seams on SkillCandidate are reserved for that.

Registering a live skill = INSERT a SkillPack row (tier=safe, status=registered).
Because the registry choke point (server/registry/service.py) reads assignable
skills straight from the SkillPack table, that INSERT makes the skill instantly
listed + equippable (no seeds file, no reseed).

Self-manages its own AsyncSessionLocal sessions, like evolution_loop.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import SkillCandidate, Spawn, SkillPack
from server.orchestrator import dispatcher
from server.registry import service as registry_service
from server.services import evaluator, replay_set

logger = logging.getLogger(__name__)

MAX_SKILL_BYTES = 15 * 1024  # Hermes hygiene: skills stay <=15 KB
_MIN_BODY_CHARS = 80
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Non-terminal candidate states: a key held in one of these blocks a new draft.
_NON_TERMINAL = ("observing", "proposed")


def validate(key: str, name: str, description: str, body: str) -> list[str]:
    """Return human-readable validation errors (empty list = valid)."""
    errors: list[str] = []
    if not key or not _KEY_RE.match(key):
        errors.append("key must be non-empty lowercase letters, digits and hyphens (e.g. 'my-skill')")
    if not (name or "").strip():
        errors.append("name is required")
    if not (description or "").strip():
        errors.append("description is required")
    body = body or ""
    if "## Trigger" not in body:
        errors.append("body must contain a '## Trigger' section")
    if len(body) < _MIN_BODY_CHARS:
        errors.append(f"body is too short (need at least {_MIN_BODY_CHARS} characters)")
    if len(body.encode("utf-8")) > MAX_SKILL_BYTES:
        errors.append(f"body exceeds {MAX_SKILL_BYTES // 1024} KB limit")
    return errors


async def create_candidate(
    *,
    key: str,
    name: str,
    category: str,
    description: str,
    body: str,
    source: str = "skill_creator",
) -> SkillCandidate:
    """Validate + insert a new SkillCandidate (status='observing').

    Raises ValueError on invalid input, or if the key collides with a live
    SkillPack or a non-terminal (observing/proposed) candidate.
    """
    errors = validate(key, name, description, body)
    if errors:
        raise ValueError("; ".join(errors))

    async with db_session.AsyncSessionLocal() as db:
        if await db.get(SkillPack, key) is not None:
            raise ValueError(f"a live skill with key '{key}' already exists")
        existing = (await db.execute(
            select(SkillCandidate).where(
                SkillCandidate.key == key,
                SkillCandidate.status.in_(_NON_TERMINAL),
            )
        )).scalars().first()
        if existing is not None:
            raise ValueError(f"a skill candidate with key '{key}' is already in progress")
        cand = SkillCandidate(
            key=key, name=name, category=category, description=description,
            body=body, source=source, status="observing",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
    return cand


# We inject the CANDIDATE body the SAME way an equipped skill's body reaches a spawn's
# system prompt — via the SHARED dispatcher._skill_technique_block (see _inject_skill_body
# below) — so evaluate_candidate is a true equip-this-skill vs not counterfactual and the
# two injection points never drift.


def _persona(spawn: Spawn) -> str:
    """Persona string for the compare-judge, mirroring evolution_loop._persona."""
    return (f"role: {spawn.persona_role or ''}\ntone: {spawn.persona_tone or ''}\n"
            f"{spawn.system_prompt or ''}")


def _inject_skill_body(base_prompt: str, name: str, body: str, *,
                       key: str | None = None, has_scripts: bool = False) -> str:
    """Append `body` to `base_prompt` exactly as an equipped skill reaches the system
    prompt in dispatcher._equipment_block_from: the SHARED _skill_technique_block under a
    "Your techniques:" header (short skills inline whole; long skills get summary + TOC +
    read_skill hint bounded by _SKILL_BLOCK_LIMIT; script-bearing skills get a run hint).
    Reusing the one helper keeps the eval-injection and the real dispatch-injection from
    drifting — the skill-on eval stays a faithful counterfactual of really equipping this."""
    body = (body or "").strip()
    if not body:
        return base_prompt
    block = dispatcher._skill_technique_block(name, body, has_scripts=has_scripts, key=key or name)
    return f"{base_prompt}\n\nYour techniques:\n{block}"


async def _val_outputs(spawn_id: int, system_prompt_override: str, val: list[dict]) -> dict:
    """Run `system_prompt_override` over val, return {run_id: output}. Mirrors
    evolution_loop._val_outputs (skill-off baseline outputs on held-out val)."""
    out: dict = {}
    for it in val:
        gen = await dispatcher.dispatch(
            "skill-eval", spawn_id=spawn_id, task_brief=it["task"],
            system_prompt_override=system_prompt_override, persist=False,
        )
        out[it["run_id"]] = gen.get("full_output", "")
    return out


async def evaluate_candidate(candidate_id: int, target_spawn_id: int, *,
                             min_samples: int = 8) -> dict:
    """Real-data eval gate: move an `observing` candidate to `proposed` only if
    equipping its body clears the performance-not-decreased gate on the target
    spawn's REAL scored runs.

    The observation period IS the spawn accumulating real scored runs: we replay
    them at eval time (no shadow live-testing). Until `min_samples` real val samples
    exist, we stay `observing` and record the shortfall. Once enough exist, we run a
    true equip-this-skill (skill-on) vs normal-prompt (skill-off) counterfactual over
    the held-out val set and gate on it. Passing → `proposed` (human-confirmable);
    the human confirm (promote_candidate) is still the ultimate gate — this INFORMS it.

    Self-manages DB sessions like evolution_loop. Never crashes: dispatch/eval
    failures degrade to a not-passed gate (mirrors evolution_loop's I1 handling).
    """
    async with db_session.AsyncSessionLocal() as db:
        cand = await db.get(SkillCandidate, candidate_id)
        if cand is None:
            return {"ok": False, "reason": "candidate not found"}
        if cand.status != "observing":
            return {"ok": False, "reason": f"candidate is {cand.status}"}
        cand_key, cand_name, cand_body = cand.key, cand.name, cand.body

        spawn = await db.get(Spawn, target_spawn_id)
        if spawn is None:
            return {"ok": False, "reason": "spawn not found"}
        # Read eagerly-loaded columns only (spawn is used after this session closes).
        skill_off_prompt = spawn.system_prompt or "You are a helpful assistant."
        persona = _persona(spawn)

    split = await replay_set.build_split(target_spawn_id)
    val = split["val"]

    # Observation gate: the spawn's real scored runs ARE the samples. Not enough yet →
    # do NOT evaluate; record the shortfall and stay observing.
    if len(val) < min_samples:
        shortfall = {"observed": len(val), "need": min_samples}
        async with db_session.AsyncSessionLocal() as db:
            cand = await db.get(SkillCandidate, candidate_id)
            if cand is not None:
                cand.samples = shortfall
                cand.evidence = {"gate": {"passed": False, "reason": "insufficient", **shortfall}}
                await db.commit()
        return {"ok": True, "status": "observing",
                "gate": {"passed": False,
                         "reason": f"insufficient real samples (have {len(val)}, need {min_samples})",
                         "aggregate": None}}

    skill_on_prompt = _inject_skill_body(
        skill_off_prompt, cand_name, cand_body,
        key=cand_key, has_scripts=registry_service.skill_has_scripts(cand_key))

    # Faithful counterfactual: skill-off baseline outputs vs skill-on candidate, over the
    # SAME held-out val runs. Degrade to a not-passed gate on any dispatch/eval failure.
    try:
        baseline_outputs = await _val_outputs(target_spawn_id, skill_off_prompt, val)
        res = await evaluator.evaluate(
            spawn_id=target_spawn_id, persona=persona,
            candidate_prompt=skill_on_prompt, replay_items=val,
            baseline_outputs=baseline_outputs,
        )
    except Exception as exc:  # noqa: BLE001  -- I1: never crash; degrade to not-passed
        logger.warning("skill candidate eval failed, degrading to no-pass: %s", exc)
        res = {"items": [], "aggregate": None,
               "gate": {"passed": False, "reason": f"eval failed: {exc}", "aggregate": None}}

    gate = res["gate"]
    val_run_ids = [it["run_id"] for it in val]
    async with db_session.AsyncSessionLocal() as db:
        cand = await db.get(SkillCandidate, candidate_id)
        if cand is None:
            return {"ok": False, "reason": "candidate not found"}
        cand.evidence = res
        cand.samples = val_run_ids
        if gate["passed"]:
            cand.status = "proposed"
        new_status = cand.status
        await db.commit()

    agg = res.get("aggregate") or {}
    return {"ok": True, "status": new_status, "gate": gate,
            "evidence_summary": {"key": cand_key, "samples": val_run_ids,
                                 "aggregate": agg.get("overall") if isinstance(agg, dict) else None}}


async def promote_candidate(candidate_id: int) -> dict:
    """Human-gated register: turn a candidate into a real live SkillPack.

    Normal path is observe -> evaluate_candidate -> proposed -> promote, but promote
    still accepts BOTH observing|proposed: the human confirm is the ultimate gate; the
    eval only INFORMS it.

    INSERTs SkillPack(tier='safe', status='registered', body=...) — which is what
    makes it listed + equippable — then marks the candidate 'promoted'.
    """
    async with db_session.AsyncSessionLocal() as db:
        cand = await db.get(SkillCandidate, candidate_id)
        if cand is None:
            return {"ok": False, "reason": "candidate not found"}
        if cand.status not in _NON_TERMINAL:
            return {"ok": False, "reason": f"already {cand.status}"}
        if await db.get(SkillPack, cand.key) is not None:
            return {"ok": False, "reason": f"a live skill with key '{cand.key}' already exists"}

        db.add(SkillPack(
            key=cand.key, name=cand.name, category=cand.category,
            description=cand.description, tier="safe", status="registered",
            body=cand.body,
        ))
        cand.status = "promoted"
        cand.promoted_at = datetime.utcnow()
        await db.commit()
        return {"ok": True, "key": cand.key}


async def reject_candidate(candidate_id: int) -> dict:
    """Mark a candidate 'rejected' (terminal)."""
    async with db_session.AsyncSessionLocal() as db:
        cand = await db.get(SkillCandidate, candidate_id)
        if cand is None:
            return {"ok": False, "reason": "candidate not found"}
        cand.status = "rejected"
        await db.commit()
        return {"ok": True}


async def list_candidates(status: str | None = None) -> list[SkillCandidate]:
    async with db_session.AsyncSessionLocal() as db:
        q = select(SkillCandidate).order_by(SkillCandidate.id.desc())
        if status is not None:
            q = q.where(SkillCandidate.status == status)
        return list((await db.execute(q)).scalars().all())
