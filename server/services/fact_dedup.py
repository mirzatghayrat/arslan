"""Exact-normalized dedup for user_facts. DESTRUCTIVE (deletes rows) — only ever
invoked explicitly via POST /facts/dedup, never on boot / write path / timer."""
from __future__ import annotations

import difflib
import logging

from sqlalchemy import select, text as sa_text

from server.db import session as db_session
from server.db.models import UserFact

logger = logging.getLogger(__name__)

_SIM_THRESHOLD = 0.85          # 0.6 → 0.85:短 CJK 事实(喜欢猫/喜欢狗=0.667)不再误撞
_MIN_CONTAINMENT_LEN = 8       # containment 仅当两串均 >= 8 字符(短串禁用)


def norm(content: str) -> str:
    """Normalization key: trim + collapse inner whitespace + ASCII-lowercase
    (CJK unaffected by lower())."""
    return " ".join((content or "").split()).lower()


async def existing_norms() -> set[str]:
    """Active-only (superseded_by IS NULL): a superseded row's content must never
    block a new write from being inserted (it would look like a live duplicate
    of a fact that's actually dead)."""
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            sa_text("SELECT content FROM user_facts WHERE superseded_by IS NULL"))).all()
    return {norm(r[0]) for r in rows}


def similar(a: str, b: str) -> bool:
    """Deterministic near-dup: exact-norm equal; containment only when BOTH sides
    >= _MIN_CONTAINMENT_LEN chars; or difflib ratio >= _SIM_THRESHOLD. difflib is
    used (not token overlap) because it works across CJK. No embeddings (v1)."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if min(len(na), len(nb)) >= _MIN_CONTAINMENT_LEN and (na in nb or nb in na):
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= _SIM_THRESHOLD


async def exact_norm_dup(db, content: str) -> UserFact | None:  # noqa: ANN001
    """Return an ACTIVE existing fact (superseded_by IS NULL) whose normalized
    content EXACTLY equals `content`'s. First phase of the two-phase write check
    (exact→merge / fuzzy→coexist). Active-only: a superseded row must never be
    treated as a live duplicate target. Fail-open: any error → None (the write
    proceeds)."""
    try:
        target = norm(content)
        rows = (await db.execute(
            select(UserFact).where(UserFact.superseded_by.is_(None)))).scalars().all()
        for row in rows:
            if norm(row.content) == target:
                return row
        return None
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("exact_norm_dup failed; treating as no-dup", exc_info=True)
        return None


async def find_near_dup(db, content: str) -> UserFact | None:  # noqa: ANN001
    """Return an ACTIVE existing fact that is a near-duplicate (exact OR fuzzy) of
    `content`, else None. Active-only: a superseded row must never be treated as
    a live near-dup target. Fail-open: any error → None (treated as no dup, so
    the write proceeds). NOTE: this returns the FIRST similar row in scan order,
    which may be a fuzzy sibling even when an exact-norm dup exists elsewhere in
    the table — callers that need to distinguish exact-merge from fuzzy-coexist
    must run `exact_norm_dup` as an independent first phase, not re-derive
    exactness from this call's result (see memory.save_facts / two-phase)."""
    try:
        rows = (await db.execute(
            select(UserFact).where(UserFact.superseded_by.is_(None)))).scalars().all()
        for row in rows:
            if similar(content, row.content):
                return row
        return None
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("find_near_dup failed; treating as no-dup", exc_info=True)
        return None


async def _supersede_targets(db) -> set[int]:  # noqa: ANN001
    """Ids referenced as the WINNER of some supersede pointer (any user_facts.id
    that appears as another row's superseded_by). These must never be deleted by
    dedup — doing so would leave the pointing row's superseded_by dangling."""
    rows = (await db.execute(sa_text(
        "SELECT DISTINCT superseded_by FROM user_facts WHERE superseded_by IS NOT NULL"))).all()
    return {r[0] for r in rows}


async def dedup_merge_facts() -> int:
    """One-shot backfill: collapse existing near-dup groups (keep earliest, bump its
    confidence per collapsed sibling, delete the rest). Active-only scan (a
    superseded row is dead history, never a merge candidate) and never deletes a
    row that is itself a supersede-pointer TARGET (would dangle the pointer) —
    such a row survives as a coexisting duplicate instead. Returns rows deleted.
    Best-effort."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            rows = list((await db.execute(
                select(UserFact).where(UserFact.superseded_by.is_(None)).order_by(UserFact.id)
            )).scalars().all())
            targets = await _supersede_targets(db)
            kept: list[UserFact] = []
            dup_ids: list[int] = []
            for row in rows:
                match = next((k for k in kept if similar(row.content, k.content)), None)
                if match is None:
                    kept.append(row)
                elif row.id in targets:
                    kept.append(row)  # can't delete a supersede target; keep as coexisting dup
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
    Active-only scan (superseded rows are dead history, excluded) and never
    deletes a row that is itself a supersede-pointer TARGET (would dangle the
    pointer) — such a row survives even if it norm-duplicates an earlier row.
    Returns number deleted. Best-effort: any failure logs and returns 0."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            rows = (await db.execute(sa_text(
                "SELECT id, content FROM user_facts WHERE superseded_by IS NULL ORDER BY id"))).all()
            targets = await _supersede_targets(db)
            seen: set[str] = set()
            dup_ids: list[int] = []
            for rid, content in rows:
                k = norm(content)
                if k in seen:
                    if rid not in targets:
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
