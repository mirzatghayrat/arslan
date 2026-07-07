"""Exact-normalized dedup for user_facts. DESTRUCTIVE (deletes rows) — only ever
invoked explicitly via POST /facts/dedup, never on boot / write path / timer."""
from __future__ import annotations

import difflib
import logging

from sqlalchemy import select, text as sa_text

from server.db import session as db_session
from server.db.models import UserFact

logger = logging.getLogger(__name__)

_SIM_THRESHOLD = 0.6


def norm(content: str) -> str:
    """Normalization key: trim + collapse inner whitespace + ASCII-lowercase
    (CJK unaffected by lower())."""
    return " ".join((content or "").split()).lower()


async def existing_norms() -> set[str]:
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(sa_text("SELECT content FROM user_facts"))).all()
    return {norm(r[0]) for r in rows}


def similar(a: str, b: str) -> bool:
    """Deterministic near-dup: exact-norm equal, OR one normalized string contains
    the other, OR difflib ratio >= threshold. difflib is used (not token overlap)
    because it works across CJK — Chinese runs share no whole-run tokens even when
    the sentences are near-identical. No embeddings (v1)."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= _SIM_THRESHOLD


async def find_near_dup(db, content: str) -> UserFact | None:  # noqa: ANN001
    """Return an existing fact that is a near-duplicate of `content`, else None.
    Fail-open: any error → None (treated as no dup, so the write proceeds)."""
    try:
        rows = (await db.execute(select(UserFact))).scalars().all()
        for row in rows:
            if similar(content, row.content):
                return row
        return None
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("find_near_dup failed; treating as no-dup", exc_info=True)
        return None


async def dedup_merge_facts() -> int:
    """One-shot backfill: collapse existing near-dup groups (keep earliest, bump its
    confidence per collapsed sibling, delete the rest). Returns rows deleted.
    Best-effort."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            rows = list((await db.execute(select(UserFact).order_by(UserFact.id))).scalars().all())
            kept: list[UserFact] = []
            dup_ids: list[int] = []
            for row in rows:
                match = next((k for k in kept if similar(row.content, k.content)), None)
                if match is None:
                    kept.append(row)
                else:
                    match.confidence = min(1.0, (match.confidence or 0.6) + 0.1)
                    dup_ids.append(row.id)
            for rid in dup_ids:
                await db.execute(sa_text("DELETE FROM user_facts WHERE id = :i"), {"i": rid})
            await db.commit()
            return len(dup_ids)
    except Exception as exc:  # noqa: BLE001
        logger.warning("dedup_merge_facts failed (non-fatal): %s", exc)
        return 0


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
