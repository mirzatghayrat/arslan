"""Classify each preference into a FIXED semantic category via the LLM. Fail-open:
classify_one → 其他 (never blocks a write, never raises). Backfill mirrors
embed_missing: single-flight, best-effort, and honest — a real provider outage
aborts (surfaced via _state['error']) instead of silently mass-labeling 其他.
Fire-and-forget scheduling holds task refs so a bare create_task can't be GC'd
mid-flight. classify_ids/schedule are staged for CL-T4 write-time wiring — not yet
called from any write path."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text as sa_text

from server.db import session as db_session
from server.services.llm_factory import build_adapter

logger = logging.getLogger(__name__)

FACT_CATEGORIES = ("身份背景", "沟通偏好", "领域兴趣", "任务需求", "想建的分身", "其他")
_SYSTEM = (
    "你是一个分类器。把用户的一条长期偏好归到且仅归到以下类别之一,只输出类别名,不要多余字:\n"
    + " / ".join(FACT_CATEGORIES)
)

_state: dict = {"running": False, "done": 0, "total": 0, "error": None}
_bg_tasks: set[asyncio.Task] = set()


def classify_status() -> dict:
    return dict(_state)


async def _classify_with(adapter, content: str) -> str:  # noqa: ANN001
    """Raw LLM call + enum match. NO try/except — raises on provider failure so
    callers can distinguish a real outage from an illegal-but-answered reply."""
    resp = await adapter.chat(system=_SYSTEM, user=content)
    reply = (resp.content or "").strip()
    for c in FACT_CATEGORIES:
        if c in reply:
            return c
    return "其他"


async def classify_one(content: str) -> str:
    """Return one of FACT_CATEGORIES. Fail-open → 其他 on any error / illegal reply."""
    try:
        adapter = await build_adapter(role="converse")
        return await _classify_with(adapter, content)
    except Exception as exc:  # noqa: BLE001 — classification is never fatal
        logger.warning("classify_one failed (non-fatal → 其他): %s", exc)
        return "其他"


async def classify_missing(batch_size: int = 32) -> int:
    """Backfill category for facts where category IS NULL. Single-flight; COUNT
    first so a no-NULL DB returns instantly. Builds ONE adapter up front and uses
    the raising _classify_with, so a real provider failure aborts the backfill
    (with _state['error'] set) and leaves remaining rows NULL for retry — instead
    of silently mass-labeling everything 其他. Best-effort."""
    if _state["running"]:
        return 0
    _state.update(running=True, done=0, total=0, error=None)
    done = 0
    try:
        adapter = await build_adapter(role="converse")  # built once, reused across the batch
        async with db_session.AsyncSessionLocal() as db:
            _state["total"] = (await db.execute(sa_text(
                "SELECT COUNT(*) FROM user_facts WHERE category IS NULL"))).scalar_one()
        while True:
            async with db_session.AsyncSessionLocal() as db:
                rows = (await db.execute(sa_text(
                    "SELECT id, content FROM user_facts WHERE category IS NULL LIMIT :n"),
                    {"n": batch_size})).all()
                if not rows:
                    break
                for rid, content in rows:
                    cat = await _classify_with(adapter, content)  # RAISES on provider failure
                    await db.execute(sa_text("UPDATE user_facts SET category = :c WHERE id = :id"),
                                     {"c": cat, "id": rid})
                await db.commit()
                done += len(rows)
                _state["done"] = done
    except Exception as exc:  # noqa: BLE001 — backfill is non-fatal; surface via _state
        logger.warning("classify_missing aborted (non-fatal): %s", exc)
        _state["error"] = str(exc)
    finally:
        _state["running"] = False
    return done


def schedule(coro) -> None:
    """Fire-and-forget with ref retention (GC-safe), for write-time + boot backfill."""
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)


async def classify_ids(ids: list[int]) -> None:
    """Classify specific fact ids. Staged for CL-T4 write-time fire-and-forget —
    not yet called from any write path. Best-effort."""
    for fid in ids:
        try:
            async with db_session.AsyncSessionLocal() as db:
                row = (await db.execute(sa_text(
                    "SELECT content FROM user_facts WHERE id = :id AND category IS NULL"),
                    {"id": fid})).first()
                if not row:
                    continue
                cat = await classify_one(row[0])
                await db.execute(sa_text("UPDATE user_facts SET category = :c WHERE id = :id"),
                                 {"c": cat, "id": fid})
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("classify_ids(%s) failed (non-fatal): %s", fid, exc)
