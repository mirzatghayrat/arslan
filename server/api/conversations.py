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
    for scope, provider, model, tin, tout, est, total, _ts in items:
        tokens_total += total
        estimated_any = estimated_any or est
        usd = item_usd(model, tin, tout, est, provider)
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



def _distill_event(*, distilled: int, failed: int) -> tuple[str, dict]:
    """(summary, ref) for a manual-distillation recap event.

    The summary is a KEY and the counts live in `ref`, because this string is
    PERSISTED (recap_service.log_event writes it to ConversationEvent.summary)
    and rendered verbatim by the recap list. A Chinese sentence written here
    stayed Chinese forever, in every interface language.

    🔴 PARTIAL BY NATURE, and the other half cannot be fixed from here: rows
    ALREADY written hold their original Chinese sentence. This changes what is
    written from now on. The interface therefore has to render both shapes —
    translate when the summary is a known key, show the stored text otherwise —
    and that fallback is not temporary scaffolding, it is how old rows stay
    readable.

    Two keys rather than one: the original wording distinguished a clean run
    from one with failures, and collapsing them would drop that distinction.
    """
    ref = {"manual": True, "distilled": distilled, "failed": failed}
    key = "recap.distill.manual_with_failures" if failed else "recap.distill.manual"
    return key, ref


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

    report = await distill_service.distill_session_detailed(conversation_id)
    n = report.distilled
    failed = [{"spawn_id": o.spawn_id, "reason": o.reason} for o in report.outcomes if o.failed]

    summary, ref = _distill_event(distilled=n, failed=len(failed))
    await recap_service.log_event(conversation_id, "distill", ref, summary)
    # `distilled_spawns` stays an INT: the frontend toast reads it numerically
    # (web/src/App.tsx) and client.types.ts types it that way. `failed_spawns` is
    # additive — before it, a total failure and a clean no-op both reported 0.
    return {"ok": True, "distilled_spawns": n, "failed_spawns": failed}


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
