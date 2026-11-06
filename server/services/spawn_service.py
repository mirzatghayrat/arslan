"""Spawn persistence and DTO mapping over the database. DELETE-BY: v0.1.64, with C7c-4."""
from __future__ import annotations

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.models import ChatMessage, Spawn
from server.schemas import ChatMessageOut, SpawnDetailOut, SpawnOut


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
        is_default=bool(getattr(spawn, "is_default", False)),
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


async def _has_active_chat(session: AsyncSession, spawn_id: int) -> bool:
    return bool((await session.execute(
        select(exists().where(ChatMessage.spawn_id == spawn_id, ChatMessage.archived == False))  # noqa: E712
    )).scalar())


async def list_spawns(session: AsyncSession) -> list[SpawnOut]:
    result = await session.execute(select(Spawn).order_by(Spawn.created_at))
    rows = result.scalars().all()
    out_list = []
    for s in rows:
        out = to_summary(s)
        out.has_active_chat = await _has_active_chat(session, s.id)
        out_list.append(out)
    return out_list


async def get_detail(session: AsyncSession, spawn_id: int) -> SpawnDetailOut | None:
    spawn = await session.get(Spawn, spawn_id)
    if spawn is None:
        return None
    msgs = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.spawn_id == spawn_id)
        .order_by(ChatMessage.id)
    )
    detail = to_detail(spawn, list(msgs.scalars().all()))
    # Resolve the seeds this spawn was composed from (config.seed_refs) for display.
    seed_refs = (spawn.config or {}).get("seed_refs") if isinstance(spawn.config, dict) else None
    if seed_refs:
        from server.schemas import SeedRefOut
        from server.services import persona_seed_service
        resolved = await persona_seed_service.get_by_slugs([str(s) for s in seed_refs])
        detail.seeds = [SeedRefOut(**r) for r in resolved]
    return detail


async def load_all_spawns() -> list[Spawn]:
    """Load every Spawn row ordered by id, managing its own session.

    Unlike the other functions in this module (which accept a session as a
    parameter), this helper opens and closes its own AsyncSessionLocal session.
    Use it in call-sites that don't already hold an open session — for example,
    the orchestrator's dedup check before create.
    """
    from server.db import session as db_session

    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(select(Spawn).order_by(Spawn.id))
        return list(rows.scalars().all())


async def create_spawn(session: AsyncSession, **fields) -> Spawn:
    """Insert a spawn row. Used by the build WebSocket and test seeding."""
    spawn = Spawn(**fields)
    session.add(spawn)
    await session.commit()
    await session.refresh(spawn)
    return spawn
