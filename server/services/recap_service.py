"""Conversation growth-event log + recap read. log_event is best-effort — a missing
conversation_id or any error is swallowed so it never touches the user's turn."""
from __future__ import annotations

import logging

from server.db import session as db_session
from server.db.models import ConversationEvent

logger = logging.getLogger(__name__)


async def log_event(conversation_id: str | None, kind: str, ref: dict | None, summary: str) -> None:
    if not conversation_id:
        return
    try:
        async with db_session.AsyncSessionLocal() as db:
            db.add(ConversationEvent(conversation_id=conversation_id, kind=kind,
                                     ref=ref, summary=(summary or "")[:400]))
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — growth logging is never fatal
        logger.warning("recap log_event failed (non-fatal): %s", exc)


async def count_events(conversation_id: str | None, kind: str) -> int:
    """Cheap SELECT COUNT of a conversation's events of one kind (0 on any error) —
    PA-4 uses it for the repeated_confirmation running counter."""
    if not conversation_id:
        return 0
    try:
        from sqlalchemy import func, select

        async with db_session.AsyncSessionLocal() as db:
            n = (await db.execute(
                select(func.count()).select_from(ConversationEvent).where(
                    ConversationEvent.conversation_id == conversation_id,
                    ConversationEvent.kind == kind))).scalar()
        return int(n or 0)
    except Exception as exc:  # noqa: BLE001 — counting is never fatal
        logger.warning("recap count_events failed (non-fatal): %s", exc)
        return 0


async def get_recap(conversation_id: str) -> dict:
    """Merge this conversation's runs (from the runs table) and growth events into
    one timeline, newest first, with a small summary. Runs are NOT duplicated into
    conversation_events — they're joined in here at read time."""
    from sqlalchemy import select

    from server.db.models import Run

    async with db_session.AsyncSessionLocal() as db:
        runs = (await db.execute(
            select(Run).where(Run.conversation_id == conversation_id))).scalars().all()
        events = (await db.execute(
            select(ConversationEvent).where(
                ConversationEvent.conversation_id == conversation_id))).scalars().all()

    items: list[dict] = []
    for r in runs:
        items.append({
            "kind": "run",
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "run_id": r.id, "spawn_name": r.spawn_name, "user_message": r.user_message,
            "overall_score": r.overall_score, "total_ms": r.total_ms,
        })
    for e in events:
        items.append({
            "kind": e.kind,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "ref": e.ref, "summary": e.summary,
        })
    items.sort(key=lambda i: i["created_at"] or "", reverse=True)

    scored = [r.overall_score for r in runs if r.status == "scored" and r.overall_score is not None]
    return {
        "summary": {
            "run_count": len(runs),
            "avg_score": round(sum(scored) / len(scored), 2) if scored else None,
            "growth_count": len(events),
        },
        "items": items,
    }
