"""Distill know-how (心得) from concrete signals ONLY — a distill recap event, a
user correction (Feedback), or a repeated successful run pattern. The LLM turns a
REAL signal into one crisp lesson; it never invents. Every learning carries a
non-empty source_ref and the whole thing is fail-open: producing nothing beats
producing something fake."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import text as sa_text

from server.db import session as db_session
from server.db.models import Learning
from server.services.fact_dedup import norm, similar
from server.services.llm_factory import build_adapter

logger = logging.getLogger(__name__)

_SYS = ("把下面这段真实发生的事,提炼成一句可复用的做事心得(不超过 40 字,中文,"
        "只依据给到的内容,不要编造)。只输出这句话本身。")


def _get_adapter():
    return build_adapter(role="summarize")


async def _write(content: str, label: str, source_kind: str, source_ref: dict,
                 spawn_id: int | None) -> int:
    content = (content or "").strip()
    if not content:
        return 0
    try:
        async with db_session.AsyncSessionLocal() as db:
            # Scanner #5 (brain-P1 Task 3, BLOCKER #2): active-only — a superseded
            # learning must never block/merge-collide with a new write. Fetches
            # (id, content), not just content — Task 4's rule-supersede needs the id.
            existing = (await db.execute(sa_text(
                "SELECT id, content FROM learnings WHERE superseded_by IS NULL"))).all()
            target = norm(content)
            if any(norm(c) == target for _id, c in existing):
                return 0                                    # 精确重复:跳过(不变)
            fuzzy = [c for _id, c in existing if similar(content, c)]
            if fuzzy:
                logger.info("learning: near-dup coexist (P1 will propose supersede): %r ~ %r",
                            content, fuzzy[0])
            row = Learning(content=content, label=(label or content)[:60],
                           source_kind=source_kind, source_ref=source_ref,
                           spawn_id=spawn_id, confidence=0.6,
                           valid_from=datetime.utcnow())
            db.add(row)
            await db.commit()
            await db.refresh(row)
            rid = row.id
            await db.execute(sa_text("INSERT INTO learnings_fts (rowid, text) VALUES (:r, :t)"),
                             {"r": rid, "t": content})
            await db.commit()
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("learning _write failed (non-fatal): %s", exc)
        return 0


async def _distill_one(signal_text: str, label: str, source_kind: str,
                       source_ref: dict, spawn_id: int | None) -> int:
    if not (signal_text or "").strip():
        return 0
    try:
        adapter = _get_adapter()
        a = await adapter if hasattr(adapter, "__await__") else adapter
        resp = await a.chat(system=_SYS, user=signal_text)
        lesson = (resp.content or "").strip()
    except Exception as exc:  # noqa: BLE001 — nothing beats fake
        logger.warning("learning distill LLM failed (non-fatal): %s", exc)
        return 0
    return await _write(lesson, label, source_kind, source_ref, spawn_id)


async def distill_from_event(*, conversation_id: str, spawn_id: int | None,
                             spawn_name: str | None, signal_text: str) -> int:
    return await _distill_one(
        signal_text, label=f"{spawn_name or '分身'} 心得", source_kind="distill",
        source_ref={"conversation_id": conversation_id, "spawn_id": spawn_id},
        spawn_id=spawn_id)


async def distill_from_feedback(*, feedback_id: int, correction_text: str,
                                spawn_id: int | None = None) -> int:
    return await _distill_one(
        correction_text, label="用户纠正", source_kind="feedback",
        source_ref={"feedback_id": feedback_id}, spawn_id=spawn_id)
