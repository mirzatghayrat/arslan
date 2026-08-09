"""Exact-normalized dedup for user_facts. DESTRUCTIVE (deletes rows) — only ever
invoked explicitly via POST /facts/dedup, never on boot / write path / timer."""
from __future__ import annotations

import difflib
import json
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
    """Active-only (superseded_by IS NULL, and not marked stale): a superseded row's
    content must never block a new write from being inserted (it would look like a live
    duplicate of a fact that's actually dead).

    A stale-marked row is the same case wearing a different flag. It is excluded from
    injection and recall (memory.list_facts), so leaving it in here would make
    re-asserting the fact a silent no-op: the write returns the stale row, and the fact
    the user just restated still never reaches a prompt.

    The stale test is done in Python for the reason given in memory.list_facts — the
    JSON predicate is not worth an extension dependency at this size."""
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(sa_text(
            "SELECT content, provenance FROM user_facts WHERE superseded_by IS NULL"))).all()
    return {norm(r[0]) for r in rows if not is_stale(r[1])}


def is_stale(provenance) -> bool:  # noqa: ANN001 — dict from the ORM, str from sa_text
    """True when provenance carries stale=true — the flag mark_stale toggles.

    Fail-OPEN (unparseable ⇒ not stale): the cost of a wrong False is one duplicate row
    the user can merge; the cost of a wrong True is a fact that silently refuses to be
    saved, which is the failure this whole flag exists to avoid."""
    if not provenance:
        return False
    if isinstance(provenance, str):
        try:
            provenance = json.loads(provenance)
        except (ValueError, TypeError):
            return False
    return bool(provenance.get("stale")) if isinstance(provenance, dict) else False


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


def fuzzy_kind(new: str, old: str) -> str | None:
    """Classify the DIRECTION of a fuzzy hit (call only after `similar()` is True
    — P1 brain rule-supersede, direction lock):

    - "extension" = both norm-strings >= _MIN_CONTAINMENT_LEN AND old is contained
      in new (new is the EXTENSION of old) -> auto-supersede candidate: the new,
      more informative write auto-wins.
    - "shrink" = same length gate AND new is contained in old (new is the
      SHRUNK/less-informative version) -> never auto-wins (a downgrade must not
      auto-supersede) -> propose instead.
    - "other" = similar()-true but neither containment direction (the pure
      difflib-ratio band) -> propose.
    - None = not similar at all (`similar()` False), OR exact-norm-equal (that's
      phase 1's job in save_facts/_write's two-phase write -- it must never reach
      this classifier).
    """
    if not similar(new, old):
        return None
    nn, no = norm(new), norm(old)
    if nn == no:
        return None  # exact belongs to phase 1, must not land here
    if min(len(nn), len(no)) >= _MIN_CONTAINMENT_LEN:
        if no in nn:
            return "extension"
        if nn in no:
            return "shrink"
    return "other"


async def exact_norm_dup(db, content: str) -> UserFact | None:  # noqa: ANN001
    """Return an ACTIVE existing fact (superseded_by IS NULL) whose normalized
    content EXACTLY equals `content`'s. First phase of the two-phase write check
    (exact→merge / fuzzy→coexist). Active-only: neither a superseded row nor one marked
    stale may be treated as a live duplicate target — merging into either would raise a
    row that no injection site reads, so the restated fact would never reach a prompt.
    Fail-open: any error → None (the write proceeds)."""
    try:
        target = norm(content)
        rows = (await db.execute(
            select(UserFact).where(UserFact.superseded_by.is_(None)))).scalars().all()
        for row in rows:
            if is_stale(row.provenance):
                continue  # marked stale: excluded from injection, so not a live target
            if norm(row.content) == target:
                return row
        return None
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("exact_norm_dup failed; treating as no-dup", exc_info=True)
        return None


async def find_near_dup(db, content: str) -> UserFact | None:  # noqa: ANN001
    """Return an ACTIVE existing fact that is a near-duplicate (exact OR fuzzy) of
    `content`, else None. Active-only: neither a superseded row nor one marked stale may
    be treated as a live near-dup target (same reason as exact_norm_dup). Fail-open: any
    error → None (treated as no dup, so the write proceeds). NOTE: this returns the
    FIRST similar row in scan order, which may be a fuzzy sibling even when an
    exact-norm dup exists elsewhere in the table — callers that need to distinguish
    exact-merge from fuzzy-coexist must run `exact_norm_dup` as a first phase, not
    re-derive
    exactness from this call's result (see memory.save_facts / two-phase)."""
    try:
        rows = (await db.execute(
            select(UserFact).where(UserFact.superseded_by.is_(None)))).scalars().all()
        for row in rows:
            if is_stale(row.provenance):
                continue  # marked stale: excluded from injection, so not a live target
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
