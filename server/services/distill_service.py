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
from server.db.models import ArslanMessage, DistilledSession, Feedback, Spawn
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


async def distill_meta_upflow(spawn, new_facts: list[str]) -> str | None:
    """After per-spawn distillation, bubble ONE cross-spawn META fact up to Arslan's
    user profile. Meta = a user preference OR a domain-ownership hint
    ('X 内容找 <spawn>'). Domain depth stays in the spawn; only meta rises.

    Routes through memory.save_facts(source='upflow', provenance={"source_kind":
    "upflow", "spawn_id": ...}) — the SAME two-phase active-only dedup + mandatory
    provenance + temporal discipline every other fact write gets (brain-P1 Task 3,
    BLOCKER #1: this function used to construct UserFact directly and bypass
    save_facts entirely, so its facts landed with provenance=NULL forever and its
    own ad-hoc containment dedup scanned superseded rows as if they were live).
    Because save_facts owns its own session/commit, this is no longer atomic with
    the caller's spawn.memory_facts + DistilledSession write (a deliberate,
    already-flagged semantic upgrade — see the P1 plan's Task 3 deviation note).

    Returns the fact content actually written, or None: the LLM said nothing
    worth upflowing, OR save_facts's exact-norm dedup merge-bumped an existing
    active row instead of inserting a new one. Best-effort: any exception → None.
    """
    if not new_facts:
        return None
    try:
        prompt = (
            f"分身「{spawn.name}」(领域:{spawn.domain_category})刚学到的偏好:\n"
            + "\n".join(f"- {f}" for f in new_facts)
        )
        adapter = await build_adapter(role="judgment")
        resp = await adapter.chat(system=_META_UPFLOW_SYSTEM, user=prompt)
        fact = (resp.content or "").strip().strip('"').strip("「」").strip()
        if not fact:
            return None
        from server.orchestrator import memory
        created = await memory.save_facts(
            [{"content": fact, "source": "upflow"}],
            provenance={"source_kind": "upflow", "spawn_id": getattr(spawn, "id", None)},
        )
        return created[0].content if created else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("distill_meta_upflow(spawn=%s) failed: %s", getattr(spawn, "id", "?"), exc)
        return None


async def distill_session(conversation_id: str) -> int:
    """Distill every spawn that produced a deliverable in this conversation. Idempotent
    per (conversation, spawn). Never raises. Returns the number of spawns ACTUALLY
    distilled this call (idle/already-distilled/failed spawns are skipped and NOT counted)
    — so callers (e.g. the manual REST trigger) can report an honest count."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            spawn_ids = (await db.execute(
                select(ArslanMessage.spawn_id).where(
                    ArslanMessage.conversation_id == conversation_id,
                    ArslanMessage.role == "spawn_summary",
                    ArslanMessage.spawn_id.isnot(None),
                ).distinct()
            )).scalars().all()
        n = 0
        for spawn_id in spawn_ids:
            if await _distill_one(conversation_id, int(spawn_id)):
                n += 1
        return n
    except Exception as exc:  # noqa: BLE001
        logger.warning("distill_session(%s) failed: %s", conversation_id, exc)
        return 0


async def _distill_one(conversation_id: str, spawn_id: int) -> bool:
    """Distill one spawn's material for this conversation. Returns True iff facts were
    actually written (and the idempotency marker persisted); False when skipped —
    already-distilled, spawn gone, nothing to distill, or LLM failure."""
    async with db_session.AsyncSessionLocal() as db:
        already = (await db.execute(select(DistilledSession).where(
            DistilledSession.conversation_id == conversation_id,
            DistilledSession.spawn_id == spawn_id))).scalar_one_or_none()
        if already is not None:
            return False
        spawn = await db.get(Spawn, spawn_id)
        if spawn is None:
            return False
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
        return False  # nothing to distill

    new_facts = await distill_facts(existing, signals)
    if new_facts is None:
        return False  # distillation failed — write nothing + no marker, so it retries next session

    async with db_session.AsyncSessionLocal() as db:
        spawn = await db.get(Spawn, spawn_id)
        if spawn is not None:
            spawn.memory_facts = new_facts
            # Best-effort metaknowledge upflow: bubble ONE cross-spawn meta-fact up to
            # Arslan's user profile. A failure here must not break the per-spawn distill.
            # NOTE: save_facts (which this now routes through) owns its own session/
            # commit, independent of this block's — see distill_meta_upflow's docstring.
            await distill_meta_upflow(spawn, new_facts)
        db.add(DistilledSession(conversation_id=conversation_id, spawn_id=spawn_id))
        await db.commit()
    return True


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
