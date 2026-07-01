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

import re
from datetime import datetime

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import SkillCandidate, SkillPack

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


async def promote_candidate(candidate_id: int) -> dict:
    """Human-gated register: turn a candidate into a real live SkillPack.

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
