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
from server.schemas import ConversationUsageOut, RecapOut, ScopeUsageOut

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/conversations/{conversation_id}/usage", response_model=ConversationUsageOut)
async def conversation_usage(conversation_id: str) -> ConversationUsageOut:
    """S3-M3: cumulative token/USD usage for ONE conversation — live spawn runs
    (scope "spawn") + usage_ledger rows (answer/router/judge/…). Honesty: usd_total
    sums only priceable items (known-price model, non-estimated tokens) and is None
    when nothing was priceable; usd_partial says some tokens carry no USD figure."""
    from server.api.usage import fetch_usage_items, item_usd

    items = await fetch_usage_items(conversation_id=conversation_id)

    tokens_total = 0
    usd_total: float | None = None
    usd_partial = False
    estimated_any = False
    by_scope: dict[str, dict] = {}
    for scope, _provider, model, tin, tout, est, total, _ts in items:
        tokens_total += total
        estimated_any = estimated_any or est
        usd = item_usd(model, tin, tout, est)
        s = by_scope.setdefault(scope, {"tokens_total": 0, "usd": None})
        s["tokens_total"] += total
        if usd is None:
            usd_partial = True
        else:
            usd_total = (usd_total or 0.0) + usd
            s["usd"] = (s["usd"] or 0.0) + usd
    return ConversationUsageOut(
        tokens_total=tokens_total, usd_total=usd_total,
        usd_partial=usd_partial, estimated_any=estimated_any,
        by_scope=[ScopeUsageOut(scope=scope, **agg) for scope, agg in sorted(
            by_scope.items(), key=lambda kv: kv[1]["tokens_total"], reverse=True)],
    )


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
    Deliberately KEEPS `runs` + `router_decisions` + `usage_ledger` (audit/diagnosis
    and cost-accounting data must survive conversation deletion, mirroring how audit
    rows survive spawn deletion).
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
