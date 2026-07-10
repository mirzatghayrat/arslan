"""Skill forge: author a skill draft and, on human confirm, register it as a
real, live, equippable library skill.

Mirrors the offline-evolution SHAPE (candidate -> gate -> proposal -> human
confirm; never auto-promote). Slice 1 IS the spine: the gate is the human
confirm (promote_candidate).

S2 E8 — the candidate eval gate is now the SAME paired ReplayGate the evolution
loop uses (replay_gate.run_gate over replay_gate.build_corpus): equipping the
skill (skill-ON prompt, arm B) vs the spawn's plain prompt (skill-OFF, arm A)
judged on the HOLDOUT split only (N>=10, >=60% win-rate, per-dim, real floor,
length, tier). This kills the old structural deadlock — the private
`len(val)<min_samples` observation gate whose default (8) exceeded the val_cap
(6) so a candidate could never leave 'observing'. There is deliberately NO
skill-specific gate: skill and evolution share run_gate verbatim.

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
from server.services import replay_gate

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
    # Candidate-eval context has NO wired-toolset view (we only inject the skill body, not the
    # spawn's final wired tools), so we can't know if read_skill/run_python are reachable here.
    # Pass availability=False → the shared helper uses honest fallback wording that never points
    # at a tool the spawn may not have, rather than fabricating a wired set.
    block = dispatcher._skill_technique_block(
        name, body, has_scripts=has_scripts, key=key or name,
        read_skill_available=False, run_python_available=False)
    return f"{base_prompt}\n\nYour techniques:\n{block}"


async def evaluate_candidate(candidate_id: int, target_spawn_id: int, *,
                             baseline_started_at=None) -> dict:
    """Real-data eval gate: move an `observing` candidate to `proposed` only if
    EQUIPPING its body beats not-equipping it on the SAME paired ReplayGate the
    evolution loop uses.

    Baseline arm (skill OFF) = the target spawn's current system_prompt. Candidate
    arm (skill ON) = that prompt with the skill body injected exactly as real
    dispatch injects an equipped skill (`_inject_skill_body`). The two arms replay
    over `replay_gate.build_corpus` (real scored runs + current synthetic tasks,
    split-aware) and are judged by `replay_gate.run_gate` on the HOLDOUT split only
    (N>=10, >=60% win-rate, per-dim non-regression, real floor, length cap, tier) —
    the identical gate + thresholds evolution gates its prompt edits with. Passing →
    `proposed` (human-confirmable); the human confirm (promote_candidate) is still
    the ultimate gate — this INFORMS it.

    `baseline_started_at` is the clean-corpus start; E9 wires it from settings. For
    now it defaults to None here AND in evolution_loop, so both callers assemble the
    corpus over the same set of runs.

    Self-manages DB sessions like evolution_loop. Never crashes: any gate/replay
    failure degrades to a not-passed gate (mirrors evolution_loop's I1 handling).
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

    skill_on_prompt = _inject_skill_body(
        skill_off_prompt, cand_name, cand_body,
        key=cand_key, has_scripts=registry_service.skill_has_scripts(cand_key))

    # The SAME holdout-only paired gate evolution runs — skill-ON (candidate, arm B) vs
    # skill-OFF (baseline, arm A) over the shared real+synthetic corpus. Degrade to a
    # not-passed gate on any build/replay/judge failure; never crash (evolution I1).
    try:
        async with db_session.AsyncSessionLocal() as db:
            corpus = await replay_gate.build_corpus(
                db, target_spawn_id, baseline_started_at=baseline_started_at)
            result = await replay_gate.run_gate(
                db, spawn_id=target_spawn_id, candidate_prompt=skill_on_prompt,
                baseline_prompt=skill_off_prompt, corpus=corpus, persona=persona)
    except Exception as exc:  # noqa: BLE001  -- I1: never crash; degrade to not-passed
        logger.warning("skill candidate ReplayGate failed, degrading to no-pass: %s", exc)
        async with db_session.AsyncSessionLocal() as db:
            cand = await db.get(SkillCandidate, candidate_id)
            if cand is not None:
                cand.evidence = {"passed": False, "reason": f"gate failed: {exc}"}
                await db.commit()
        return {"ok": True, "status": "observing",
                "gate": {"passed": False, "reason": f"gate failed: {exc}", "aggregate": None}}

    # Store the GateResult evidence the SAME way evolution_loop stores it on a proposal
    # (gate.user_facing()) so a skill candidate's evidence renders identically to a prompt
    # proposal (E7 PromotionCard reads real_delta / synthetic_delta / pairs / evidence_tier).
    uf = result.user_facing()
    async with db_session.AsyncSessionLocal() as db:
        cand = await db.get(SkillCandidate, candidate_id)
        if cand is None:
            return {"ok": False, "reason": "candidate not found"}
        cand.evidence = uf
        cand.samples = list(uf.get("protected_run_ids", []))
        if result.passed:
            cand.status = "proposed"
        new_status = cand.status
        await db.commit()

    return {"ok": True, "status": new_status,
            "gate": {"passed": result.passed, "reason": result.reason, "aggregate": uf}}


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
