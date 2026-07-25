"""Classify each preference into a FIXED semantic category + short label via ONE
few-shot LLM call. Fail-open: classify_one → (其他, None) (never blocks a write,
never raises). Backfill mirrors embed_missing: single-flight, best-effort, and
honest — a real provider outage aborts (surfaced via _state['error']) instead of
silently mass-labeling 其他. Backfill judges on label IS NULL (also re-derives
category, fixing stale/wrong labels from before this call returned a label).
Fire-and-forget scheduling holds task refs so a bare create_task can't be GC'd
mid-flight. classify_ids/schedule are wired into write paths (CL-T4): memory.py
(save_facts/add_manual_fact), distill_service.py (distill_meta_upflow), and a
non-blocking boot backfill in main.py's lifespan."""
from __future__ import annotations

import asyncio
import json
import logging
import re

from sqlalchemy import text as sa_text

from server.db import session as db_session
from server.services.llm_factory import build_adapter

logger = logging.getLogger(__name__)

FACT_CATEGORIES = ("身份背景", "沟通偏好", "领域兴趣", "任务需求", "想建的分身", "其他")
_SYSTEM = (
    "你是用户长期偏好的分类器兼摘要器。对给定的一条偏好,做两件事:\n"
    "1) 归到且仅归到以下类别之一:\n"
    "   身份背景 = 籍贯/民族/公司/职位/所在地(例:「用户来自甲城,母语是甲语」「在 Acme 做客户经理」)\n"
    "   沟通偏好 = 说话风格/语言/格式偏好(例:「喜欢中文沟通」「不喜欢列表式回答」)\n"
    "   领域兴趣 = 关注的行业/主题(例:「关注广告科技」「对加密货币感兴趣」)\n"
    "   任务需求 = 想让 AI 帮做的具体事(例:「每日抓 GitHub Trending 出分析」「要 OKX 永续合约调研 PPT」)\n"
    "   想建的分身 = 明确说要创建一个…分身/助手(例:「想建一个处理 GitHub 项目分析的分身」)\n"
    "   其他 = 都不属于时的兜底\n"
    "2) 摘一个 3-8 字的短标签(label),抓这条偏好的核心关键词,语言随原文"
    "(例:「股票交易助手」「LinkedIn 优化」「GitHub Trending 分析」)。\n"
    '只输出一行 JSON,形如 {"category": "任务需求", "label": "GitHub Trending 分析"},不要多余字。'
)

_state: dict = {"running": False, "done": 0, "total": 0, "error": None}
_bg_tasks: set[asyncio.Task] = set()


def classify_status() -> dict:
    return dict(_state)


_LABEL_NULL = "label IS NULL"  # backfill/write-time judge: a fact still needs (re)labeling


def _fallback_label(label: str | None, content: str) -> str:
    """Guarantee a non-NULL label so a just-labeled row won't be re-picked by backfill:
    the LLM's short label, else the (codepoint-safe) truncated content."""
    return label or (content or "")[:40]


def _parse(reply: str) -> tuple[str, str | None]:
    """Parse the LLM reply into (category, label). Fail-open: bad/illegal → (其他, None)
    for category; JSON preferred, substring category match as fallback when no JSON."""
    reply = (reply or "").strip()
    m = re.search(r"\{.*\}", reply, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            c = str(obj.get("category", "")).strip()
            cat = c if c in FACT_CATEGORIES else "其他"
            lb = str(obj.get("label", "") or "").strip()
            return cat, (lb[:40] or None)
        except Exception:  # noqa: BLE001 — bad JSON is fail-open, not fatal
            pass
    cat = "其他"
    for c in FACT_CATEGORIES:
        if c in reply:
            cat = c
            break
    return cat, None


async def _classify_with(adapter, content: str) -> tuple[str, str | None]:  # noqa: ANN001
    """Raw LLM call + parse → (category, label). NO try/except — raises on provider
    failure so callers distinguish a real outage from an illegal-but-answered reply."""
    resp = await adapter.chat(system=_SYSTEM, user=content)
    return _parse(resp.content or "")


async def classify_one(content: str) -> tuple[str, str | None]:
    """Return (category, label). Fail-open → (其他, None) on any error / illegal reply."""
    try:
        adapter = await build_adapter(role="converse")
        return await _classify_with(adapter, content)
    except Exception as exc:  # noqa: BLE001 — classification is never fatal
        logger.warning("classify_one failed (non-fatal → 其他): %s", exc)
        return "其他", None


async def classify_missing(batch_size: int = 32) -> int:
    """Backfill (category, label) for facts where label IS NULL. Single-flight;
    COUNT first so a fully-labeled DB returns instantly. Builds ONE adapter up
    front and uses the raising _classify_with, so a real provider failure aborts
    (with _state['error'] set) and leaves rows label-NULL for retry — instead of
    silently mass-labeling. Re-derives category too (fixes stale/wrong labels).
    Best-effort."""
    if _state["running"]:
        return 0
    _state.update(running=True, done=0, total=0, error=None)
    done = 0
    try:
        async with db_session.AsyncSessionLocal() as db:
            total = (await db.execute(sa_text(
                f"SELECT COUNT(*) FROM user_facts WHERE {_LABEL_NULL}"))).scalar_one()
        _state["total"] = total
        if total == 0:
            return 0  # zero-cost on a fully-labeled DB; don't even build an adapter
        adapter = await build_adapter(role="converse")  # built once, reused across the batch
        while True:
            async with db_session.AsyncSessionLocal() as db:
                rows = (await db.execute(sa_text(
                    f"SELECT id, content FROM user_facts WHERE {_LABEL_NULL} LIMIT :n"),
                    {"n": batch_size})).all()
                if not rows:
                    break
                for rid, content in rows:
                    cat, label = await _classify_with(adapter, content)  # RAISES on outage
                    await db.execute(sa_text(
                        "UPDATE user_facts SET category = :c, label = :l WHERE id = :id"),
                        {"c": cat, "l": _fallback_label(label, content), "id": rid})
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
    """(Re)classify + label specific fact ids (label IS NULL). Called fire-and-forget
    from write paths via schedule(). Best-effort: on a provider outage, skip the row
    (leave label NULL for boot backfill) rather than persisting a mislabel."""
    for fid in ids:
        try:
            async with db_session.AsyncSessionLocal() as db:
                row = (await db.execute(sa_text(
                    f"SELECT content FROM user_facts WHERE id = :id AND {_LABEL_NULL}"),
                    {"id": fid})).first()
                if not row:
                    continue
                adapter = await build_adapter(role="converse")
                cat, label = await _classify_with(adapter, row[0])  # raises on outage
                await db.execute(sa_text(
                    "UPDATE user_facts SET category = :c, label = :l WHERE id = :id"),
                    {"c": cat, "l": _fallback_label(label, row[0]), "id": fid})
                await db.commit()
        except Exception as exc:  # noqa: BLE001 — leave NULL for boot backfill on failure
            logger.warning("classify_ids(%s) failed (non-fatal, left NULL): %s", fid, exc)
