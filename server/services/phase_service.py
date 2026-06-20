"""Staged-orchestration phase state per conversation (one pending proposal at a time)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select

from server.db import session as db_session
from server.db.models import SpawnPhase


async def set_proposing(conversation_id: str, spawn_id: int, direction: str) -> None:
    """Upsert: clear any existing pending proposal for the conversation, then insert."""
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            delete(SpawnPhase).where(SpawnPhase.conversation_id == conversation_id)
        )
        db.add(
            SpawnPhase(
                conversation_id=conversation_id,
                spawn_id=spawn_id,
                phase="proposing",
                direction=direction,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        await db.commit()


async def get_pending(conversation_id: str) -> dict | None:
    """Return the pending proposal for the conversation, or None if none exists."""
    async with db_session.AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(SpawnPhase).where(SpawnPhase.conversation_id == conversation_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return {"spawn_id": row.spawn_id, "phase": row.phase, "direction": row.direction}


async def clear(conversation_id: str, spawn_id: int | None = None) -> None:
    """Remove the pending proposal for the conversation."""
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            delete(SpawnPhase).where(SpawnPhase.conversation_id == conversation_id)
        )
        await db.commit()
