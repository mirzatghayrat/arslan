"""Session-end distillation: consolidate a spawn's session signals into ≤8 behavioral
preferences stored in Spawn.memory_facts. Best-effort, background, never raises.

Step-1 finding (verdict source): per-session 👍/👎 verdicts/feedback are recorded by
`evolution_service.record_feedback` into the per-spawn on-disk EvolutionEngine store
(`spawns_dir/<name>/.evolution`), NOT cleanly per-conversation. The DB `Feedback` table
IS written (server/api/evolution.py) but keyed by `session_id="spawn-{spawn_id}"` — i.e.
per-spawn, not per (conversation_id, spawn_id). So verdicts are not cleanly queryable for a
given distill session; we DEGRADE to conversation-only signals (user messages + the spawn's
deliverables from ArslanMessage), which are always present per conversation. Verdicts remain
an additive signal that can be wired in later if a per-conversation feedback key lands.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ArslanMessage, DistilledSession, Spawn
from server.orchestrator.json_protocol import parse_json_object
from server.services.llm_factory import build_adapter
from server.services.prompts.distill import DISTILL_SYSTEM

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
        existing = list(spawn.memory_facts or [])

    # Conversation-only signals (see Step-1 note in module docstring): verdicts are not
    # cleanly per-(conversation,spawn) queryable, so we feed the conversation material only.
    signals = "用户消息:\n" + "\n".join(u for u in user_msgs if u) + \
              "\n\n分身产出:\n" + "\n".join(d for d in deliverables if d)
    if not deliverables and not user_msgs:
        return  # nothing to distill

    new_facts = await distill_facts(existing, signals)
    if new_facts is None:
        return  # distillation failed — write nothing + no marker, so it retries next session

    async with db_session.AsyncSessionLocal() as db:
        spawn = await db.get(Spawn, spawn_id)
        if spawn is not None:
            spawn.memory_facts = new_facts
        db.add(DistilledSession(conversation_id=conversation_id, spawn_id=spawn_id))
        await db.commit()
