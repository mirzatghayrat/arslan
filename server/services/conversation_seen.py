"""INB4 (v0.1.64): which message of a conversation the user has seen in the window (table `conversation_seen`, migration 0083).

phone_reads.describe reads the marks: a clean reply or a job done newer than the mark is "done, not seen".
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.models import ArslanMessage, ConversationSeen


async def mark(db: AsyncSession, conversation_id: str, message_id: int | None = None) -> int:
    """Seen up to `message_id`, by default the conversation's newest message. A mark never moves back: two windows, or an
    older request arriving late, keep the newer one."""
    if message_id is None:
        message_id = await db.scalar(select(func.max(ArslanMessage.id))
                                     .where(ArslanMessage.conversation_id == conversation_id)) or 0
    stmt = insert(ConversationSeen).values(conversation_id=conversation_id, seen_message_id=message_id,
                                           seen_at=datetime.utcnow())
    await db.execute(stmt.on_conflict_do_update(index_elements=["conversation_id"], set_={
        "seen_message_id": func.max(ConversationSeen.seen_message_id, stmt.excluded.seen_message_id),
        "seen_at": stmt.excluded.seen_at}))
    await db.commit()
    return await db.scalar(select(ConversationSeen.seen_message_id).where(ConversationSeen.conversation_id == conversation_id))


async def marks(db: AsyncSession, conversation_ids: list[str]) -> dict[str, int]:
    rows = await db.execute(select(ConversationSeen.conversation_id, ConversationSeen.seen_message_id)
                            .where(ConversationSeen.conversation_id.in_(conversation_ids)))
    return dict(rows.all())
