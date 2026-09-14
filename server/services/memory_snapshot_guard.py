"""Deletion fences for in-flight derived snapshots; never carries memory text."""
from sqlalchemy import exists, select

from server.db.models import MemoryStoreState
from server.db import session as db_session


async def capture(db) -> tuple[str, int] | None:
    state = await db.get(MemoryStoreState, 1)
    return (state.instance_id, state.deletion_epoch) if state else None


def unchanged(token):
    """SQL predicate evaluated atomically by the eventual INSERT or UPDATE."""
    state = select(MemoryStoreState.id).where(MemoryStoreState.id == 1)
    if token is None:
        return ~exists(state)
    identity, epoch = token
    return exists(state.where(MemoryStoreState.instance_id == identity,
                              MemoryStoreState.deletion_epoch == epoch))


async def is_current(token) -> bool:
    async with db_session.AsyncSessionLocal() as db:
        return bool(await db.scalar(select(unchanged(token))))
