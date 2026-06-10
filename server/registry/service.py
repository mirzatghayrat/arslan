"""Tier enforcement choke point. ALL spawn-capability reads/writes route through here.

Layer 1: safe_menu() — the only listing spawn-facing contexts may use.
Layer 2: assert_assignable() — the only gate on spawn_capabilities writes.
Layer 3: wired_tools_for_spawn() — the only tool resolution the loop may call.
"""
from __future__ import annotations

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import SkillPack, SpawnCapability, Tool, Toolset

_ASSIGNABLE_STATUSES = ("wired", "registered")


class NotAssignableError(Exception):
    """Raised when a capability is not in the spawn-assignable safe subset."""


def _toolset_dict(t: Toolset) -> dict:
    return {"key": t.key, "name": t.name, "description": t.description,
            "tier": t.tier, "status": t.status}


def _skill_dict(s: SkillPack) -> dict:
    return {"key": s.key, "name": s.name, "description": s.description,
            "category": s.category, "tier": s.tier, "status": s.status}


async def safe_menu() -> dict:
    """Everything a spawn may be equipped with: tier=safe, wired or registered."""
    async with db_session.AsyncSessionLocal() as db:
        ts = (await db.execute(
            select(Toolset).where(Toolset.tier == "safe",
                                  Toolset.status.in_(_ASSIGNABLE_STATUSES))
            .order_by(Toolset.key)
        )).scalars().all()
        sk = (await db.execute(
            select(SkillPack).where(SkillPack.tier == "safe",
                                    SkillPack.status.in_(_ASSIGNABLE_STATUSES))
            .order_by(SkillPack.key)
        )).scalars().all()
    return {"toolsets": [_toolset_dict(t) for t in ts],
            "skills": [_skill_dict(s) for s in sk]}


async def assert_assignable(kind: str, ref_key: str) -> None:
    """Hard server-side gate: raises unless (kind, ref_key) is safe + assignable.

    No bypass parameter exists by design (spec §2): the only holder of
    orchestrator-tier capabilities is Arslan itself, implicitly.
    """
    async with db_session.AsyncSessionLocal() as db:
        row = (
            await db.get(Toolset, ref_key) if kind == "toolset"
            else await db.get(SkillPack, ref_key) if kind == "skill"
            else None
        )
    if row is None:
        raise NotAssignableError(f"unknown {kind}: {ref_key}")
    if row.tier != "safe" or row.status not in _ASSIGNABLE_STATUSES:
        raise NotAssignableError(
            f"{kind} {ref_key} is not spawn-assignable (tier={row.tier}, status={row.status})"
        )


async def equipment_for_spawn(spawn_id: int) -> dict:
    """All equipment rows resolved against the registry (for tags/DTOs)."""
    async with db_session.AsyncSessionLocal() as db:
        caps = (await db.execute(
            select(SpawnCapability).where(SpawnCapability.spawn_id == spawn_id)
            .order_by(SpawnCapability.id)
        )).scalars().all()
        toolsets, skills = [], []
        for c in caps:
            if c.kind == "toolset":
                row = await db.get(Toolset, c.ref_key)
                if row is not None:
                    toolsets.append({**_toolset_dict(row), "grant": c.grant})
            else:
                row = await db.get(SkillPack, c.ref_key)
                if row is not None:
                    skills.append({**_skill_dict(row), "grant": c.grant})
    return {"toolsets": toolsets, "skills": skills}


async def wired_tools_for_spawn(spawn_id: int, *, current_turn: int) -> list[dict]:
    """Layer-3 gate: tools callable by this spawn RIGHT NOW.

    equipped toolsets (permanent, or temporary with expires_turn >= current_turn)
    ∩ tool.tier == "safe" ∩ tool.status == "wired".
    """
    async with db_session.AsyncSessionLocal() as db:
        caps = (await db.execute(
            select(SpawnCapability).where(
                SpawnCapability.spawn_id == spawn_id,
                SpawnCapability.kind == "toolset",
            )
        )).scalars().all()
        active_keys = [
            c.ref_key for c in caps
            if c.grant == "permanent"
            or c.expires_turn is None
            or c.expires_turn >= current_turn
        ]
        if not active_keys:
            return []
        tools = (await db.execute(
            select(Tool).where(
                Tool.toolset_key.in_(active_keys),
                Tool.tier == "safe",
                Tool.status == "wired",
            ).order_by(Tool.key)
        )).scalars().all()
    return [{"key": t.key, "description": t.description,
             "input_schema": t.input_schema or {}} for t in tools]


async def grant_temporary(spawn_id: int, ref_key: str, *, current_turn: int,
                          turns: int = 3) -> None:
    """Escalation path (b): temporary safe-only grant. Validated, idempotent."""
    await assert_assignable("toolset", ref_key)
    async with db_session.AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(SpawnCapability).where(
                SpawnCapability.spawn_id == spawn_id,
                SpawnCapability.kind == "toolset",
                SpawnCapability.ref_key == ref_key,
            )
        )).scalar_one_or_none()
        if existing is not None:
            if existing.grant == "temporary":
                existing.expires_turn = current_turn + turns
        else:
            db.add(SpawnCapability(
                spawn_id=spawn_id, kind="toolset", ref_key=ref_key,
                grant="temporary", granted_by="escalation",
                expires_turn=current_turn + turns,
            ))
        await db.commit()
