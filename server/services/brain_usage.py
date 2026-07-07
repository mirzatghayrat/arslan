"""Unified cross-cutting usage for the Second Brain (material/learning/profile).
record() is best-effort — usage is an observation signal and must never break
retrieval. usage_map() bulk-reads for the tree/detail endpoints."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import text as sa_text

from server.db import session as db_session

logger = logging.getLogger(__name__)


async def record(kind: str, ref_key: str, *, used_ref: str | None) -> None:
    """Increment usage for one entity (upsert on the (kind, ref_key) unique index).
    Fail-open: any error is swallowed — usage is never allowed to break retrieval."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            await db.execute(sa_text(
                "INSERT INTO brain_usage (kind, ref_key, usage_count, last_used_at, last_used_ref, created_at) "
                "VALUES (:k, :r, 1, :ts, :ur, :ts) "
                "ON CONFLICT(kind, ref_key) DO UPDATE SET "
                "usage_count = usage_count + 1, last_used_at = :ts, last_used_ref = :ur"),
                {"k": kind, "r": ref_key, "ts": datetime.utcnow(), "ur": used_ref})
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — usage never fatal
        logger.warning("brain_usage.record failed (non-fatal): %s", exc)


async def usage_map(keys: list[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    """Return {(kind, ref_key): {usage_count, last_used_at, last_used_ref}} for the
    subset that has rows. Missing keys are simply absent. Fail-open → {}."""
    if not keys:
        return {}
    try:
        async with db_session.AsyncSessionLocal() as db:
            rows = (await db.execute(sa_text(
                "SELECT kind, ref_key, usage_count, last_used_at, last_used_ref FROM brain_usage"))).all()
        wanted = set(keys)
        out: dict[tuple[str, str], dict] = {}
        for k, r, n, ts, ur in rows:
            if (k, r) in wanted:
                out[(k, r)] = {"usage_count": n, "last_used_at": ts, "last_used_ref": ur}
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("brain_usage.usage_map failed (non-fatal): %s", exc)
        return {}
