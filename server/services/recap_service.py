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
