"""0.1.44 one Arslan: turn a former expert into a skill Arslan applies itself.

An expert was a system prompt plus a domain. Its prompt becomes the skill's
method; nothing is deleted. The user's click is the human gate (create +
promote in one step, like promoting a reviewed candidate).
"""
from __future__ import annotations

import re

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import SkillPack, Spawn
from server.services import skill_forge


def skill_key(spawn: Spawn) -> str:
    ascii_name = re.sub(r"[^a-z0-9]+", "-", (spawn.name or "").lower()).strip("-")[:40]
    return f"expert-{spawn.id}" + (f"-{ascii_name}" if ascii_name else "")


def skill_body(spawn: Spawn) -> str:
    domain = " / ".join(x for x in (spawn.domain_category, spawn.domain_subcategory) if x)
    role = f" The work of a {spawn.persona_role}." if spawn.persona_role else ""
    head = (f"# {spawn.name}\n\n## Trigger\nUse for work in {domain or 'this area'}.{role}\n\n"
            f"## Method\n")
    room = skill_forge.MAX_SKILL_BYTES - len(head.encode()) - 64
    method = (spawn.system_prompt or "").strip().encode()[:room].decode(errors="ignore")
    return head + method + "\n"


async def list_experts() -> list[dict]:
    async with db_session.AsyncSessionLocal() as db:
        # Only experts the user made. The built-in examples were seeded on every install
        # until 0.1.48; listing them as "former experts" would show people experts they
        # never had.
        spawns = (await db.execute(
            select(Spawn).where(Spawn.is_default.is_(False)).order_by(Spawn.id))).scalars().all()
        keys = set((await db.execute(select(SkillPack.key))).scalars().all())
    return [{"id": s.id, "name": s.name, "domain": s.domain_category,
             "skill_key": skill_key(s), "converted": skill_key(s) in keys} for s in spawns]


async def convert(spawn_id: int) -> dict:
    async with db_session.AsyncSessionLocal() as db:
        spawn = await db.get(Spawn, spawn_id)
        if spawn is None:
            return {"ok": False, "code": "expert_not_found"}
        key = skill_key(spawn)
        if await db.get(SkillPack, key) is not None:
            return {"ok": True, "key": key, "already": True}
        body = skill_body(spawn)
        name, description = spawn.name, f"Method from the former expert {spawn.name}"[:200]
    if len(body) < 80 or skill_forge.validate(key, name, description, body):
        return {"ok": False, "code": "expert_prompt_too_short"}
    candidate = await skill_forge.create_candidate(key=key, name=name, category="method",
                                                   description=description, body=body, source="expert")
    promoted = await skill_forge.promote_candidate(candidate.id)
    return {"ok": bool(promoted.get("ok")), "key": key}
