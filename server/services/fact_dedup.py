"""Exact-normalized dedup for user_facts. DESTRUCTIVE (deletes rows) — only ever
invoked explicitly via POST /facts/dedup, never on boot / write path / timer."""
from __future__ import annotations

import logging

from sqlalchemy import text as sa_text

from server.db import session as db_session

logger = logging.getLogger(__name__)


def norm(content: str) -> str:
    """Normalization key: trim + collapse inner whitespace + ASCII-lowercase
    (CJK unaffected by lower())."""
    return " ".join((content or "").split()).lower()


async def existing_norms() -> set[str]:
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(sa_text("SELECT content FROM user_facts"))).all()
    return {norm(r[0]) for r in rows}


async def dedup_facts() -> int:
    """Keep the earliest (min id) row of each norm-group, delete the rest.
    Returns number deleted. Best-effort: any failure logs and returns 0."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            rows = (await db.execute(sa_text(
                "SELECT id, content FROM user_facts ORDER BY id"))).all()
            seen: set[str] = set()
            dup_ids: list[int] = []
            for rid, content in rows:
                k = norm(content)
                if k in seen:
                    dup_ids.append(rid)
                else:
                    seen.add(k)
            for rid in dup_ids:
                await db.execute(sa_text("DELETE FROM user_facts WHERE id = :id"), {"id": rid})
            await db.commit()
            return len(dup_ids)
    except Exception as exc:  # noqa: BLE001 — dedup is never fatal
        logger.warning("dedup_facts failed (non-fatal): %s", exc)
        return 0
