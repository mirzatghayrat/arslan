"""Deletion-aware model history. Display history remains untouched."""
from sqlalchemy import String, and_, cast, exists, or_, select

from server.db import session as db_session
from server.db.models import ArslanMessage, ArslanSummary, MemorySuppression


def eligible_messages(conversation_id):
    # A conversation source can have derived replies with no exact provenance.
    # Exclude its pre-deletion context conservatively, not subsequent new turns.
    suppressed = exists(select(MemorySuppression.source_kind).where(or_(
        and_(MemorySuppression.source_kind == "message_id",
             MemorySuppression.source_id == cast(ArslanMessage.id, String)),
        and_(MemorySuppression.source_kind == "run_id",
             MemorySuppression.source_id == cast(ArslanMessage.run_id, String)),
        and_(MemorySuppression.source_kind == "conversation_id",
             MemorySuppression.source_id == ArslanMessage.conversation_id,
             or_(ArslanMessage.timestamp.is_(None),
                 ArslanMessage.timestamp <= MemorySuppression.cutoff_at)),
    )))
    return select(ArslanMessage).where(
        ArslanMessage.conversation_id == conversation_id, ~suppressed)


async def dependencies_current(snapshot):
    async with db_session.AsyncSessionLocal() as db:
        for conversation_id, message_ids, summary_ids in snapshot:
            ids = tuple(message_ids)
            for offset in range(0, len(ids), 200):
                batch = ids[offset:offset + 200]
                found = set((await db.scalars(eligible_messages(conversation_id)
                    .with_only_columns(ArslanMessage.id)
                    .where(ArslanMessage.id.in_(batch)))).all())
                if found != set(batch):
                    return False
            if summary_ids:
                found = set((await db.scalars(select(ArslanSummary.id).where(
                    ArslanSummary.conversation_id == conversation_id,
                    ArslanSummary.id.in_(summary_ids)))).all())
                if found != set(summary_ids):
                    return False
    return True
