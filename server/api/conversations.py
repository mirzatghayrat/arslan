"""Conversation-scoped recap — runs + growth events merged into one timeline."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import delete

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
    """Manually trigger the SAME session-end distill pipeline the orchestrator runs
    on session-end (`distill_service.distill_session`): it selects only spawns that
    produced a deliverable (`spawn_summary`), applies the empty-guard, folds each
    into that spawn's memory_facts, and writes the per-(conversation, spawn) idempotency
    marker. We reuse that function verbatim so the manual path can never diverge from
    auto (no hand-rolled per-spawn loop). `distilled_spawns` is the honest count of
    spawns ACTUALLY distilled this call — idle/already-distilled/failed spawns are
    skipped, so it is NOT the roster size and NOT a memory-item count. A `distill`
    growth event is logged for the recap. Auth-gated."""
    from server.services import distill_service, recap_service

    n = await distill_service.distill_session(conversation_id)

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
