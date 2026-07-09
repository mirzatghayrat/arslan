"""Conversation-scoped recap — runs + growth events merged into one timeline."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import delete, distinct, select

from server.auth import require_auth
from server.db import session as db_session
from server.db.models import (
    ArslanMessage,
    ArslanSummary,
    ConversationEvent,
    ConversationSpawn,
    DistilledSession,
    SpawnPhase,
)
from server.schemas import RecapOut

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/conversations/{conversation_id}/recap", response_model=RecapOut)
async def conversation_recap(conversation_id: str) -> RecapOut:
    from server.services import recap_service

    return RecapOut(**await recap_service.get_recap(conversation_id))


@router.post("/conversations/{conversation_id}/distill")
async def conversation_distill(conversation_id: str) -> dict:
    """Manually trigger the session-end distill pipeline for one conversation:
    for every spawn that participated, fold this conversation's material into the
    spawn's memory_facts (via the same distill_service call the orchestrator uses),
    then log a `distill` growth event for the recap. Auth-gated."""
    from server.services import distill_service, recap_service

    async with db_session.AsyncSessionLocal() as db:
        spawn_ids = (await db.execute(
            select(ConversationSpawn.spawn_id).where(
                ConversationSpawn.conversation_id == conversation_id)
        )).scalars().all()
        if not spawn_ids:
            spawn_ids = (await db.execute(
                select(distinct(ArslanMessage.spawn_id)).where(
                    ArslanMessage.conversation_id == conversation_id,
                    ArslanMessage.spawn_id.isnot(None))
            )).scalars().all()

        user_msgs = (await db.execute(
            select(ArslanMessage.content).where(
                ArslanMessage.conversation_id == conversation_id,
                ArslanMessage.role == "user"))).scalars().all()

    users = "\n".join(u for u in user_msgs if u)

    n = 0
    for spawn_id in spawn_ids:
        async with db_session.AsyncSessionLocal() as db:
            deliverables = (await db.execute(
                select(ArslanMessage.display_content).where(
                    ArslanMessage.conversation_id == conversation_id,
                    ArslanMessage.role == "spawn_summary",
                    ArslanMessage.spawn_id == spawn_id))).scalars().all()
        outs = "\n".join(d for d in deliverables if d)
        signals = f"用户消息:\n{users}\n\n分身产出:\n{outs}"
        await distill_service.distill_from_signals(int(spawn_id), signals)
        n += 1

    await recap_service.log_event(
        conversation_id, "distill", {"manual": True}, f"手动蒸馏 {n} 个分身")
    return {"ok": True, "distilled_spawns": n}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> dict:
    """Purge a conversation's OWN rows across the FK-less `conversation_id` tables.
    Deliberately KEEPS `runs` + `router_decisions` (audit/diagnosis data must
    survive conversation deletion, mirroring how audit rows survive spawn deletion).
    Auth-gated (inherited from the router-level require_auth dependency)."""
    deleted: dict[str, int] = {}
    async with db_session.AsyncSessionLocal() as db:
        for model in (
            ArslanMessage,
            ArslanSummary,
            ConversationEvent,
            ConversationSpawn,
            SpawnPhase,
            DistilledSession,
        ):
            res = await db.execute(
                delete(model).where(model.conversation_id == conversation_id))
            deleted[model.__tablename__] = res.rowcount or 0
        await db.commit()
    return {"ok": True, "deleted": deleted}
