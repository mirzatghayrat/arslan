"""Session-end distillation: consolidate a spawn's session signals into ≤8 behavioral
preferences stored in Spawn.memory_facts. Best-effort, background, never raises.

Verdict source: deliverable 👍/👎 verdicts are persisted as DB `Feedback` rows keyed by the
REAL `conversation_id` (see `record_deliverable_verdict` in server/orchestrator/arslan.py),
so they ARE cleanly queryable per (conversation_id, spawn_id). We fold them into the distill
signals alongside conversation material (user messages + the spawn's deliverables from
ArslanMessage). The REST `/feedback` endpoint still writes a degenerate `spawn-{id}` key; those
rows are intentionally excluded here since they aren't tied to a specific conversation.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ArslanMessage, DistilledSession, Feedback, Spawn, UserFact
from server.orchestrator.json_protocol import parse_json_object
from server.services.llm_factory import build_adapter
from server.services.prompts.distill import DISTILL_SYSTEM

_META_UPFLOW_SYSTEM = (
    "你是 Arslan 的记忆整理器。只提炼 AT MOST 一条对【所有分身 / Arslan 本身】都有用的元知识——"
    "要么是通用的用户偏好(如「用户偏口语、忌硬广」),要么是领域归属"
    "(如「小红书类内容交给某分身」)。不要提炼只对该分身领域内部有用的细节。"
    "如果没有值得上浮的,返回空字符串。只输出一行纯文本(那条元知识或空),不要解释、不要 JSON、不要引号。"
)

logger = logging.getLogger(__name__)

_MAX_FACTS = 8


async def distill_facts(existing: list[str], signals: str) -> list[str] | None:
    """LLM-consolidate existing prefs + this session's signals → ≤8 prefs. Returns None
    on any failure (LLM error / unparseable / bad shape) so the caller can skip the write
    AND the idempotency marker — a transient failure must not permanently consume the session."""
    user = f"现有偏好:\n{existing}\n\n本次会话信号:\n{signals[:8000]}"
    try:
        adapter = await build_adapter(role="judgment")
        resp = await adapter.chat(system=DISTILL_SYSTEM, user=user)
        parsed = parse_json_object(resp.content or "") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("distill_facts failed (will retry next session): %s", exc)
        return None
    facts = parsed.get("facts")
    if not isinstance(facts, list):
        return None
    return [str(f).strip() for f in facts if str(f).strip()][:_MAX_FACTS]


async def distill_meta_upflow(db, spawn, new_facts: list[str]) -> str | None:
    """After per-spawn distillation, bubble ONE cross-spawn META fact up to Arslan's
    user profile (UserFact, source='upflow'). Meta = a user preference OR a
    domain-ownership hint ('X 内容找 <spawn>'). Domain depth stays in the spawn; only
    meta rises. Returns the fact written, or None. Dedup: skip if an existing UserFact
    already covers it (simple containment). Best-effort: any exception → None."""
    if not new_facts:
        return None
    try:
        existing = [
            (f.content or "").strip()
            for f in (await db.execute(select(UserFact))).scalars().all()
        ]
        existing = [e for e in existing if e]
        prompt = (
            f"分身「{spawn.name}」(领域:{spawn.domain_category})刚学到的偏好:\n"
            + "\n".join(f"- {f}" for f in new_facts)
            + "\n\n已有的用户画像(别重复):\n"
            + ("\n".join(f"- {e}" for e in existing) if existing else "(空)")
        )
        adapter = await build_adapter(role="judgment")
        resp = await adapter.chat(system=_META_UPFLOW_SYSTEM, user=prompt)
        fact = (resp.content or "").strip().strip('"').strip("「」").strip()
        if not fact:
            return None
        # cheap dedup guard: skip if an existing fact contains / is contained by it
        if any(fact in e or e in fact for e in existing):
            return None
        row = UserFact(content=fact, source="upflow")
        db.add(row)
        try:
            # flush (not commit) assigns row.id; the caller (_distill_one) owns the
            # commit. If that later commit rolls back, this scheduled classify targets
            # a now-nonexistent id — a safe no-op, since classify_ids matches on
            # `WHERE id=:id AND category IS NULL` and simply finds nothing.
            await db.flush()
            from server.services import fact_classify
            fact_classify.schedule(fact_classify.classify_ids([row.id]))
        except Exception:  # noqa: BLE001 — scheduling never blocks distillation
            pass
        return fact
    except Exception as exc:  # noqa: BLE001
        logger.warning("distill_meta_upflow(spawn=%s) failed: %s", getattr(spawn, "id", "?"), exc)
        return None


async def distill_session(conversation_id: str) -> None:
    """Distill every spawn that produced a deliverable in this conversation. Idempotent
    per (conversation, spawn). Never raises."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            spawn_ids = (await db.execute(
                select(ArslanMessage.spawn_id).where(
                    ArslanMessage.conversation_id == conversation_id,
                    ArslanMessage.role == "spawn_summary",
                    ArslanMessage.spawn_id.isnot(None),
                ).distinct()
            )).scalars().all()
        for spawn_id in spawn_ids:
            await _distill_one(conversation_id, int(spawn_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("distill_session(%s) failed: %s", conversation_id, exc)


async def _distill_one(conversation_id: str, spawn_id: int) -> None:
    async with db_session.AsyncSessionLocal() as db:
        already = (await db.execute(select(DistilledSession).where(
            DistilledSession.conversation_id == conversation_id,
            DistilledSession.spawn_id == spawn_id))).scalar_one_or_none()
        if already is not None:
            return
        spawn = await db.get(Spawn, spawn_id)
        if spawn is None:
            return
        deliverables = (await db.execute(select(ArslanMessage.display_content).where(
            ArslanMessage.conversation_id == conversation_id,
            ArslanMessage.role == "spawn_summary",
            ArslanMessage.spawn_id == spawn_id))).scalars().all()
        user_msgs = (await db.execute(select(ArslanMessage.content).where(
            ArslanMessage.conversation_id == conversation_id,
            ArslanMessage.role == "user"))).scalars().all()
        verdicts = (await db.execute(select(Feedback.user_action).where(
            Feedback.session_id == conversation_id,
            Feedback.spawn_id == spawn_id))).scalars().all()
        existing = list(spawn.memory_facts or [])

    # Conversation material + per-conversation 👍/👎 verdict counts (now cleanly queryable).
    ups = sum(1 for v in verdicts if v == "thumbs_up")
    downs = sum(1 for v in verdicts if v == "thumbs_down")
    feedback_line = f"\n\n用户反馈:👍×{ups} 👎×{downs}" if (ups or downs) else ""
    signals = "用户消息:\n" + "\n".join(u for u in user_msgs if u) + \
              "\n\n分身产出:\n" + "\n".join(d for d in deliverables if d) + \
              feedback_line
    if not deliverables and not user_msgs:
        return  # nothing to distill

    new_facts = await distill_facts(existing, signals)
    if new_facts is None:
        return  # distillation failed — write nothing + no marker, so it retries next session

    async with db_session.AsyncSessionLocal() as db:
        spawn = await db.get(Spawn, spawn_id)
        if spawn is not None:
            spawn.memory_facts = new_facts
            # Best-effort metaknowledge upflow: bubble ONE cross-spawn meta-fact up to
            # Arslan's user profile. A failure here must not break the per-spawn distill.
            await distill_meta_upflow(db, spawn, new_facts)
        db.add(DistilledSession(conversation_id=conversation_id, spawn_id=spawn_id))
        await db.commit()


async def distill_from_signals(spawn_id: int, signals: str) -> None:
    """Distill an EPHEMERAL session (sandbox) whose transcript lives only in memory.
    Unlike distill_session, takes signals directly (no DB query) and writes no
    DistilledSession marker (each sandbox confirm is its own one-shot session).
    Best-effort, never raises."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            spawn = await db.get(Spawn, spawn_id)
            if spawn is None:
                return
            existing = list(spawn.memory_facts or [])
        new_facts = await distill_facts(existing, signals)
        if new_facts is None:
            return
        async with db_session.AsyncSessionLocal() as db:
            spawn = await db.get(Spawn, spawn_id)
            if spawn is not None:
                spawn.memory_facts = new_facts
                await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("distill_from_signals(spawn=%s) failed: %s", spawn_id, exc)
