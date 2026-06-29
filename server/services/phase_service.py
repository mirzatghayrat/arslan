"""Staged-orchestration phase state per conversation (one pending proposal at a time)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select

from server.db import session as db_session
from server.db.models import SpawnPhase


# Sentinel spawn_id for the "clarifying" phase: while Arslan is gathering a
# create request there is no spawn yet. The spawn_phases.spawn_id column is
# NOT NULL and carries no FK to spawns, so a 0 sentinel is safe (no migration).
_CLARIFYING_SPAWN_ID = 0


async def _upsert_phase(conversation_id: str, *, spawn_id: int, phase: str, direction: str) -> None:
    """Clear any existing pending row for the conversation, then insert one
    (one pending phase per conversation)."""
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            delete(SpawnPhase).where(SpawnPhase.conversation_id == conversation_id)
        )
        db.add(
            SpawnPhase(
                conversation_id=conversation_id,
                spawn_id=spawn_id,
                phase=phase,
                direction=direction,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        await db.commit()


async def set_proposing(conversation_id: str, spawn_id: int, direction: str) -> None:
    """Upsert: clear any existing pending proposal for the conversation, then insert."""
    await _upsert_phase(conversation_id, spawn_id=spawn_id, phase="proposing", direction=direction)


async def set_clarifying(conversation_id: str) -> None:
    """Pin a 'clarifying' create phase for the conversation. While active, the
    turn model suppresses routing to existing spawns so the follow-up keeps
    clarifying."""
    await _upsert_phase(conversation_id, spawn_id=_CLARIFYING_SPAWN_ID, phase="clarifying", direction="")


async def clear_clarifying(conversation_id: str) -> None:
    """Clear a clarifying phase (alias of clear for call-site readability)."""
    await clear(conversation_id)


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
