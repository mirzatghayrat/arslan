"""0.1.44 one Arslan: turn a former expert into a skill Arslan applies itself.

An expert was a system prompt plus a domain. Its prompt becomes the skill's
method; nothing is deleted. The user's click is the human gate: the skill is
written at once (v0.1.64 CAP2a: no candidate any more), marked as the user's
(`skill_forge.AUTHORED`), so a seed retirement never deletes it (D7).
DELETE-BY: v0.1.64, with C7c-5 (its migration converts every leftover expert, using what this does).
Since C7c-5b there is no Spawn model: the rows are read as text from `spawns`, which an upgraded install keeps
until C7c-5c and a new install never has (then there is nothing to convert).
"""
from __future__ import annotations

import re

from sqlalchemy import select, text

from server.db import session as db_session
from server.db.models import SkillPack
from server.services import skill_forge

_COLUMNS = "id, name, domain_category, domain_subcategory, persona_role, system_prompt"


async def _spawns(db, where: str, params: dict) -> list:
    """Rows of the legacy `spawns` table (attribute access, as the model gave); none when it is absent."""
    if (await db.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='spawns'"))).first() is None:
        return []
    return list((await db.execute(text(f"SELECT {_COLUMNS} FROM spawns WHERE {where} ORDER BY id"), params)).all())


def skill_key(spawn) -> str:
    ascii_name = re.sub(r"[^a-z0-9]+", "-", (spawn.name or "").lower()).strip("-")[:40]
    return f"expert-{spawn.id}" + (f"-{ascii_name}" if ascii_name else "")


def skill_body(spawn) -> str:
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
        spawns = await _spawns(db, "is_default = 0", {})
        keys = set((await db.execute(select(SkillPack.key))).scalars().all())
    return [{"id": s.id, "name": s.name, "domain": s.domain_category,
             "skill_key": skill_key(s), "converted": skill_key(s) in keys} for s in spawns]


async def convert(spawn_id: int) -> dict:
    async with db_session.AsyncSessionLocal() as db:
        found = await _spawns(db, "id = :id", {"id": spawn_id})
        spawn = found[0] if found else None
        if spawn is None:
            return {"ok": False, "code": "expert_not_found"}
        key = skill_key(spawn)
        if await db.get(SkillPack, key) is not None:
            return {"ok": True, "key": key, "already": True}
        body = skill_body(spawn)
        name, description = spawn.name, f"Method from the former expert {spawn.name}"[:200]
    if len(body) < 80 or skill_forge.validate(key, name, description, body):
        return {"ok": False, "code": "expert_prompt_too_short"}
    # The former expert's own prompt (Arslan's setup, kept by the user, converted on the user's click), not
    # text read from outside in a conversation. C7c-5 decides the same for each expert it converts.
    if not await skill_forge.register(key=key, name=name, description=description, body=body, outside=False):
        return {"ok": True, "key": key, "already": True}     # converted meanwhile (another click)
    return {"ok": True, "key": key}
