"""Direct-chat lifecycle: 完结 = distill the active transcript into the spawn's
memory_facts, then archive it (keep the rows, drop them from the active history)."""
from __future__ import annotations

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ChatMessage
from server.services import distill_service


async def complete_chat(spawn_id: int) -> int:
    """Distill the spawn's active chat history into memory_facts, then mark those rows
    archived. Returns the number of messages archived (0 if there was no active chat)."""
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ChatMessage).where(
                ChatMessage.spawn_id == spawn_id, ChatMessage.archived == False  # noqa: E712
            ).order_by(ChatMessage.id)
        )).scalars().all()
        if not rows:
            return 0
        users = "\n".join(m.content for m in rows if m.role == "user" and m.content)
        outs = "\n".join(m.content for m in rows if m.role == "assistant" and m.content)
        signals = f"用户消息:\n{users}\n\n分身产出:\n{outs}"

    await distill_service.distill_from_signals(spawn_id, signals)

    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ChatMessage).where(
                ChatMessage.spawn_id == spawn_id, ChatMessage.archived == False  # noqa: E712
            )
        )).scalars().all()
        for m in rows:
            m.archived = True
        await db.commit()
        return len(rows)
