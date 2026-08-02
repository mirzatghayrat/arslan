"""Conversation-scoped recap — runs + growth events merged into one timeline."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, func, select

from server.auth import require_auth
from server.db.session import get_session
from server.db.models import (
    ArslanMessage,
    ArslanSummary,
    ConversationEvent,
    ConversationSpawn,
    DistilledSession,
    SpawnPhase,
)
from server.schemas import (
    ConversationListItem,
    ConversationUsageOut,
    RecapOut,
    ScopeUsageOut,
)

router = APIRouter(dependencies=[Depends(require_auth)])


#: How much of the opening message becomes the recovered conversation's name.
_TITLE_CHARS = 60


@router.get("/conversations", response_model=list[ConversationListItem])
async def list_conversations(
    db: AsyncSession = Depends(get_session),
) -> list[ConversationListItem]:
    """Every conversation that has messages, most recently active first.

    🔴 The point of this endpoint is DISCOVERY. Every sibling here takes the id
    as a path parameter, which silently made the frontend's localStorage the
    only record of what existed — and in the packaged app that record does not
    survive a restart. The rows were never lost; they were unreachable.

    Auth-gated by the router dependency, and that matters more here than for the
    by-id endpoints: this one hands back the user's own opening sentences
    without needing an id to be guessed first.
    """
    # 🔴 Injected session, unlike this file's older endpoints which open
    # `AsyncSessionLocal()` directly. That difference is deliberate:
    # the shared test client overrides `get_session` but NOT the module global,
    # so an endpoint built the old way silently reads the REAL user database in
    # tests. This one was caught doing exactly that — it came back with the
    # user's own conversations — and `get_session` is the codebase's normal
    # dependency anyway (spawns.py, registry.py, create.py).
    if True:
        agg = (await db.execute(
            select(ArslanMessage.conversation_id,
                   func.count(ArslanMessage.id),
                   func.max(ArslanMessage.timestamp))
            .group_by(ArslanMessage.conversation_id)
        )).all()
        if not agg:
            return []
        # Titles from the first USER message per conversation — not simply the
        # first message, which is often Arslan's greeting and would name every
        # recovered conversation the same thing.
        first_user = (await db.execute(
            select(ArslanMessage.conversation_id, func.min(ArslanMessage.id))
            .where(ArslanMessage.role == "user")
            .group_by(ArslanMessage.conversation_id)
        )).all()
        ids = [mid for _, mid in first_user]
        bodies = {}
        if ids:
            rows = (await db.execute(
                select(ArslanMessage.id, ArslanMessage.content)
                .where(ArslanMessage.id.in_(ids))
            )).all()
            by_msg = dict(rows)
            bodies = {cid: (by_msg.get(mid) or "") for cid, mid in first_user}

    out = [
        ConversationListItem(
            conversation_id=cid,
            title=" ".join((bodies.get(cid) or "").split())[:_TITLE_CHARS],
            message_count=int(n),
            last_at=last.isoformat() if last else None,
        )
        for cid, n, last in agg
    ]
    # Most recently active first. `last_at` can be None on rows predating the
    # default, so those sort last rather than blowing up the comparison.
    out.sort(key=lambda c: (c.last_at is not None, c.last_at or ""), reverse=True)
    return out


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
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Purge a conversation's OWN rows across the FK-less `conversation_id` tables.
    Deliberately KEEPS `runs` + `router_decisions` + `usage_ledger` (audit/diagnosis
    and cost-accounting data must survive conversation deletion, mirroring how audit
    rows survive spawn deletion).
    Auth-gated (inherited from the router-level require_auth dependency)."""
    deleted: dict[str, int] = {}
    # Injected session — see list_conversations for why. With this endpoint on
    # the module global and the listing on the injection, the two talked to
    # DIFFERENT databases under the shared test client: the delete landed in the
    # user's real one and the listing read a temp one. `get_session` reads the
    # module global at call time, so fixtures that patch AsyncSessionLocal keep
    # working exactly as before.
    if True:
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
