"""Idempotent registry seeding: insert-or-update by key; never deletes."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

import arslan.spawn
from arslan.spawn.skillpack import SkillPack as _SkillPackSpec
from server.db import session as db_session
from server.db.models import SkillPack, Tool, Toolset
from server.registry.seed_catalog import SKILLS, TOOLSETS

logger = logging.getLogger(__name__)

_SEEDS_DIR = Path(arslan.spawn.__file__).parent / "seeds"


def _skill_body(key: str) -> str | None:
    """Read the SKILL.md body for a seeded skill key, or None if absent/unparseable.
    Catalog tuple stays authoritative for metadata; the file provides ONLY the body."""
    md = _SEEDS_DIR / key / "SKILL.md"
    if not md.exists():
        return None
    try:
        return _SkillPackSpec.from_skill_md(md.read_text(encoding="utf-8")).body or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("seed skill body parse failed for %s: %s", key, exc)
        return None


async def seed_registry_with(db: AsyncSession) -> None:
    """Upsert the full catalog into the given session. Reclassifications ship as
    code changes and are applied on restart; rows are never deleted (user grants
    reference them)."""
    for ts in TOOLSETS:
        row = await db.get(Toolset, ts["key"])
        if row is None:
            row = Toolset(key=ts["key"])
            db.add(row)
        row.name = ts["name"]
        row.description = ts["description"]
        row.tier = ts["tier"]
        row.status = ts["status"]
        row.backend_note = ts.get("backend_note")
        for tkey, tdesc, ttier, tstatus in ts.get("tools", []):
            trow = await db.get(Tool, tkey)
            if trow is None:
                trow = Tool(key=tkey, toolset_key=ts["key"])
                db.add(trow)
            trow.toolset_key = ts["key"]
            trow.description = tdesc
            trow.tier = ttier
            trow.status = tstatus
    for key, name, category, description, tier, status in SKILLS:
        srow = await db.get(SkillPack, key)
        if srow is None:
            srow = SkillPack(key=key)
            db.add(srow)
        srow.name = name
        srow.category = category
        srow.description = description
        srow.tier = tier
        srow.status = status
        srow.body = _skill_body(key)
    await db.commit()


async def seed_registry() -> None:
    """Upsert the full catalog using the app's default session factory."""
    async with db_session.AsyncSessionLocal() as db:
        await seed_registry_with(db)
