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
        # Snapshot the exact ids we distill, and archive ONLY those. If the user keeps
        # chatting during the (slow, async) distill, those newer rows stay active — they
        # are neither archived-without-being-distilled (data loss) nor double-counted.
        ids = [m.id for m in rows]
        users = "\n".join(m.content for m in rows if m.role == "user" and m.content)
        outs = "\n".join(m.content for m in rows if m.role == "assistant" and m.content)
        signals = f"用户消息:\n{users}\n\n分身产出:\n{outs}"

    outcome = await distill_service.distill_from_signals(spawn_id, signals)
    if outcome.failed:
        # 🔴 Archiving here used to be UNCONDITIONAL: a silently-failed distillation
        # moved the transcript out of the active window with nothing learned from it —
        # real, unrecoverable data loss. Leave it active so the user can retry (this
        # path is user-triggered, so retries are human-paced; the automatic-spend risk
        # lives in the curation sweep, which has its own cap).
        return 0

    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ChatMessage).where(ChatMessage.id.in_(ids))
        )).scalars().all()
        for m in rows:
            m.archived = True
        await db.commit()
        return len(rows)
