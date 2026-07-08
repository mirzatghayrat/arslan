#!/usr/bin/env python3
"""PA-5 — equip the brainstorming skill (obra/superpowers, MIT) on Deck Master + research spawns.

Why this is an "equip" script and not a GitHub import call:
  The library ALREADY carries `brainstorming` as a seeded catalog skill
  (arslan/spawn/seeds/brainstorming/SKILL.md — adapted from
  github:obra/superpowers · skills/brainstorming/SKILL.md, MIT, © 2025 Jesse Vincent;
  upstream verified 2026-07-09 @ commit d884ae04edebef577e82ff7c4e143debd0bbec99 —
  license MIT re-checked via `gh api repos/obra/superpowers`; attribution lives in
  THIRD_PARTY_NOTICES.md and the seed frontmatter `source:` field).
  The boot seeder upserts that row by key on every start, and
  server/services/skill_import.py refuses duplicate keys by design — so re-importing
  verbatim would either be rejected (same key) or duplicate the methodology under a
  second key. The missing piece is the EQUIP: spawn_capabilities grants.

What it does (idempotent — re-running is a no-op):
  1. Ensures the `brainstorming` SkillPack row exists (recreated from the same
     seed-catalog entry + seeds/ SKILL.md the boot seeder uses, if ever absent).
  2. Grants it to Deck Master, Research Analyst and Financial Research Analyst
     (kind='skill', grant='permanent', granted_by='user' — the same row shape as
     the existing user-granted skills on those spawns).
  3. Prints the pack row + all brainstorming capability rows for verification.

Run against the real DB:
    ARSLAN_DATA_DIR=data .venv/bin/python scripts/import_brainstorming_skill.py

Takes effect per-dispatch without a backend restart: build_spawn_system
(server/orchestrator/dispatcher.py) reads equipment + skill bodies from the DB
on every dispatch.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from server.db.models import SkillPack, Spawn, SpawnCapability  # noqa: E402

SKILL_KEY = "brainstorming"
TARGET_SPAWN_NAMES = ("Deck Master", "Research Analyst", "Financial Research Analyst")


async def ensure_brainstorming_equipped(db: AsyncSession) -> dict:
    """Idempotent core: ensure the pack row exists + the three grants. Commits."""
    result: dict = {"pack_created": False, "equipped": [], "already": [], "missing_spawns": []}

    pack = await db.get(SkillPack, SKILL_KEY)
    if pack is None:
        # Recreate from the SAME source of truth the boot seeder uses (catalog + seeds/).
        from server.registry.seed_catalog import SKILLS
        from server.registry.seeder import _skill_body

        entry = next((s for s in SKILLS if s[0] == SKILL_KEY), None)
        body = _skill_body(SKILL_KEY)
        if entry is None or body is None:
            raise RuntimeError(
                "brainstorming seed missing from seed_catalog/seeds — refusing to invent content"
            )
        key, name, category, description, tier, status = entry
        db.add(SkillPack(key=key, name=name, category=category,
                         description=description, tier=tier, status=status, body=body))
        result["pack_created"] = True

    for spawn_name in TARGET_SPAWN_NAMES:
        spawn = (await db.execute(
            select(Spawn).where(Spawn.name == spawn_name)
        )).scalar_one_or_none()
        if spawn is None:
            result["missing_spawns"].append(spawn_name)
            continue
        existing = (await db.execute(
            select(SpawnCapability).where(
                SpawnCapability.spawn_id == spawn.id,
                SpawnCapability.kind == "skill",
                SpawnCapability.ref_key == SKILL_KEY,
            )
        )).scalar_one_or_none()
        if existing is not None:
            result["already"].append((spawn.id, spawn_name))
            continue
        db.add(SpawnCapability(spawn_id=spawn.id, kind="skill", ref_key=SKILL_KEY,
                               grant="permanent", granted_by="user"))
        result["equipped"].append((spawn.id, spawn_name))

    await db.commit()
    return result


async def _main() -> int:
    from server.db import session as db_session

    async with db_session.AsyncSessionLocal() as db:
        res = await ensure_brainstorming_equipped(db)

        pack = await db.get(SkillPack, SKILL_KEY)
        caps = (await db.execute(
            select(SpawnCapability).where(
                SpawnCapability.kind == "skill",
                SpawnCapability.ref_key == SKILL_KEY,
            ).order_by(SpawnCapability.spawn_id)
        )).scalars().all()

    print(f"pack_created={res['pack_created']}  equipped={res['equipped']}  "
          f"already={res['already']}  missing_spawns={res['missing_spawns']}")
    print(f"skill_packs: key={pack.key} name={pack.name} category={pack.category} "
          f"tier={pack.tier} status={pack.status} body_len={len(pack.body or '')}")
    for c in caps:
        print(f"spawn_capabilities: id={c.id} spawn_id={c.spawn_id} kind={c.kind} "
              f"ref_key={c.ref_key} grant={c.grant} granted_by={c.granted_by} "
              f"expires_turn={c.expires_turn}")
    if res["missing_spawns"]:
        print(f"WARNING: spawns not found by name: {res['missing_spawns']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
