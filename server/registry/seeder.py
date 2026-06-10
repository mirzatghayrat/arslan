"""Idempotent registry seeding: insert-or-update by key; never deletes."""
from __future__ import annotations

from server.db import session as db_session
from server.db.models import SkillPack, Tool, Toolset
from server.registry.seed_catalog import SKILLS, TOOLSETS


async def seed_registry() -> None:
    """Upsert the full catalog. Reclassifications ship as code changes and are
    applied on restart; rows are never deleted (user grants reference them)."""
    async with db_session.AsyncSessionLocal() as db:
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
        await db.commit()
