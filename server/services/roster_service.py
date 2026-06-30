"""Per-conversation spawn roster: who belongs to a conversation (workbench #2)."""
from __future__ import annotations

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ConversationSpawn, Spawn
from server.services import phase_service


async def join(conversation_id: str, spawn_id: int, *, via: str) -> bool:
    """Add a spawn to a conversation's roster. Idempotent: an existing membership is kept
    as-is (a later auto-`routed` join never downgrades a manual `invited` membership).

    Returns True if a new row was inserted, False if the spawn was already a member."""
    async with db_session.AsyncSessionLocal() as db:
        existing = await db.execute(
            select(ConversationSpawn).where(
                ConversationSpawn.conversation_id == conversation_id,
                ConversationSpawn.spawn_id == spawn_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return False
        db.add(ConversationSpawn(conversation_id=conversation_id, spawn_id=spawn_id, joined_via=via))
        await db.commit()
        return True


async def is_member(conversation_id: str, spawn_id: int) -> bool:
    """Whether `spawn_id` is currently in the conversation's roster."""
    async with db_session.AsyncSessionLocal() as db:
        row = await db.execute(
            select(ConversationSpawn).where(
                ConversationSpawn.conversation_id == conversation_id,
                ConversationSpawn.spawn_id == spawn_id,
            )
        )
        return row.scalar_one_or_none() is not None


async def clear(conversation_id: str) -> int:
    """Remove ALL spawns from a conversation's roster (session-ephemeral reset).

    Roster membership is session context, not durable: it is cleared when a new app
    session resumes a conversation (and on session end). Spawn personas live in the
    Ledger and are untouched; only the per-conversation membership rows are removed.
    Returns the number of rows removed."""
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(
            select(ConversationSpawn).where(ConversationSpawn.conversation_id == conversation_id)
        )
        members = rows.scalars().all()
        for m in members:
            await db.delete(m)
        await db.commit()
        return len(members)


async def kick(conversation_id: str, spawn_id: int) -> bool:
    """Remove a spawn from the roster. Returns True if a row was removed. History is untouched."""
    async with db_session.AsyncSessionLocal() as db:
        row = await db.execute(
            select(ConversationSpawn).where(
                ConversationSpawn.conversation_id == conversation_id,
                ConversationSpawn.spawn_id == spawn_id,
            )
        )
        obj = row.scalar_one_or_none()
        if obj is None:
            return False
        await db.delete(obj)
        await db.commit()
        return True


async def list_roster(conversation_id: str) -> list[dict]:
    """Roster members with resolved name + live status ('awaiting_confirm' | 'idle')."""
    pending = await phase_service.get_pending(conversation_id)
    pending_spawn = (pending or {}).get("spawn_id") if (pending or {}).get("phase") == "proposing" else None
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(
            select(ConversationSpawn)
            .where(ConversationSpawn.conversation_id == conversation_id)
            .order_by(ConversationSpawn.joined_at)
        )
        members = rows.scalars().all()
        out = []
        for m in members:
            spawn = await db.get(Spawn, m.spawn_id)
            out.append({
                "spawn_id": m.spawn_id,
                "spawn_name": spawn.name if spawn else None,
                "joined_via": m.joined_via,
                "status": "awaiting_confirm" if m.spawn_id == pending_spawn else "idle",
            })
        return out
