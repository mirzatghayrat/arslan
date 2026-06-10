"""Spawn persistence and DTO mapping over the database."""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.models import ChatMessage, Spawn
from server.schemas import ChatMessageOut, SpawnDetailOut, SpawnOut


def normalize_capabilities(value: Any) -> list[str]:
    """Coerce an LLM-produced `capabilities` value into a clean string list.

    Models are inconsistent: a draft's capabilities may come back as a JSON array,
    a comma-joined string (incl. the full-width comma '，'), or be missing entirely.
    Downstream consumers (the create-spawn card, the DB column) expect a list, so we
    normalize at the source.
    """
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,，]", value) if part.strip()]
    return []


def normalize_draft(draft: Any) -> dict:
    """Return a copy of a suggested-spawn draft with `capabilities` coerced to a list."""
    if not isinstance(draft, dict):
        return {}
    normalized = dict(draft)
    normalized["capabilities"] = normalize_capabilities(draft.get("capabilities"))
    return normalized


def _normalize_name(name: str) -> str:
    """Lowercase, trim, and strip a trailing '-<digits>' uniqueness suffix."""
    return re.sub(r"-\d+$", "", (name or "").strip().lower())


def find_overlap(draft: dict, spawns: list) -> dict | None:
    """Return {spawn_id, name, axes} for an existing spawn that overlaps the draft, else None.

    Overlap fires on (1) normalized NAME equality, or (2) full 'category.subcategory' domain
    equality. Coarse domain_category alone NEVER matches (finance.equity-research and
    finance.crypto are distinct). `axes` is left [] here; callers may merge the LLM's axes.
    """
    dname = _normalize_name(draft.get("name") or "")
    ddomain = (draft.get("domain") or "").strip().lower()
    _dcat, _, dsub = ddomain.partition(".")
    for s in spawns:
        if dname and _normalize_name(s.name) == dname:
            return {"spawn_id": s.id, "name": s.name, "axes": []}
        if dsub and s.domain_subcategory:
            s_full = f"{s.domain_category}.{s.domain_subcategory}".strip().lower()
            if s_full == ddomain:
                return {"spawn_id": s.id, "name": s.name, "axes": []}
    return None


def build_system_prompt(draft: dict) -> str:
    role = draft.get("persona_role") or "a helpful assistant"
    tone = draft.get("persona_tone") or ""
    domain = draft.get("domain") or ""
    parts = [f"You are {role}."]
    if tone:
        parts.append(f"Tone: {tone}.")
    if domain:
        parts.append(f"Domain focus: {domain}.")
    return " ".join(parts)


def _domain(spawn: Spawn) -> str:
    if spawn.domain_subcategory:
        return f"{spawn.domain_category}.{spawn.domain_subcategory}"
    return spawn.domain_category


def to_summary(spawn: Spawn) -> SpawnOut:
    return SpawnOut(
        id=spawn.id,
        name=spawn.name,
        domain=_domain(spawn),
        capabilities=spawn.capabilities or [],
        template_used=spawn.template_used,
        generation_level=spawn.generation_level or 1,
        created_at=spawn.created_at.isoformat() if spawn.created_at else "",
        updated_at=spawn.updated_at.isoformat() if spawn.updated_at else "",
    )


def to_detail(spawn: Spawn, messages: list[ChatMessage]) -> SpawnDetailOut:
    return SpawnDetailOut(
        **to_summary(spawn).model_dump(),
        persona_role=spawn.persona_role,
        persona_tone=spawn.persona_tone,
        system_prompt=spawn.system_prompt or "",
        messages=[
            ChatMessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                timestamp=m.timestamp.isoformat() if m.timestamp else "",
            )
            for m in messages
        ],
    )


async def list_spawns(session: AsyncSession) -> list[SpawnOut]:
    result = await session.execute(select(Spawn).order_by(Spawn.created_at))
    return [to_summary(s) for s in result.scalars().all()]


async def get_spawn(session: AsyncSession, spawn_id: int) -> Spawn | None:
    return await session.get(Spawn, spawn_id)


async def get_detail(session: AsyncSession, spawn_id: int) -> SpawnDetailOut | None:
    spawn = await session.get(Spawn, spawn_id)
    if spawn is None:
        return None
    msgs = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.spawn_id == spawn_id)
        .order_by(ChatMessage.id)
    )
    return to_detail(spawn, list(msgs.scalars().all()))


async def update_config(
    session: AsyncSession,
    spawn_id: int,
    *,
    system_prompt: str | None = None,
    persona_tone: str | None = None,
    persona_role: str | None = None,
    config: dict | None = None,
) -> Spawn | None:
    spawn = await session.get(Spawn, spawn_id)
    if spawn is None:
        return None
    if system_prompt is not None:
        spawn.system_prompt = system_prompt
    if persona_tone is not None:
        spawn.persona_tone = persona_tone
    if persona_role is not None:
        spawn.persona_role = persona_role
    if config is not None:
        spawn.config = config
    await session.commit()
    await session.refresh(spawn)
    return spawn


async def delete_spawn(session: AsyncSession, spawn_id: int) -> bool:
    spawn = await session.get(Spawn, spawn_id)
    if spawn is None:
        return False
    await session.delete(spawn)
    await session.commit()
    return True


async def create_spawn(session: AsyncSession, **fields) -> Spawn:
    """Insert a spawn row. Used by the build WebSocket and test seeding."""
    spawn = Spawn(**fields)
    session.add(spawn)
    await session.commit()
    await session.refresh(spawn)
    return spawn


async def create_spawn_unique(session: AsyncSession, *, name: str, **fields) -> Spawn:
    """Create a spawn, auto-suffixing the name (name-2, name-3, ...) to satisfy the
    UNIQUE constraint instead of raising IntegrityError on a collision."""
    base = name or "new-spawn"
    candidate = base
    suffix = 2
    while (
        await session.execute(select(Spawn.id).where(Spawn.name == candidate))
    ).first() is not None:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return await create_spawn(session, name=candidate, **fields)
