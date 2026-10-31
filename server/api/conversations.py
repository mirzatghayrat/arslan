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
    PermissionGrant,
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
    """Every conversation that has messages, most recently active first; quick questions (Q1) are left
    out: they have a list of their own on the phone and never reach the sidebar."""
    return await conversation_list(db)


async def conversation_list(db: AsyncSession, *, quick: bool = False) -> list[ConversationListItem]:
    """Every conversation that has messages, most recently active first: the ordinary ones, or with
    `quick` only the stored quick questions (Q1, migration 0071).

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
    from server.db.companion_models import ConversationContext
    from server.services import phone_ids
    kinds = dict((await db.execute(select(ConversationContext.id, ConversationContext.kind).where(
        ConversationContext.id.in_([c.conversation_id for c in out])))).all())
    # Q1b (#486 review, G1): one the phone made with no kind stored is read as quick (phone_ids.kind_of).
    out = [c for c in out if (phone_ids.kind_of(c.conversation_id, kinds.get(c.conversation_id)) == "quick") is quick]
    # What each one is and how it stands — the sidebar's glyphs, the phone's task list — and the
    # phone's own conversation named Remote rather than after its first message.
    from server.services import phone_reads
    extra = await phone_reads.describe(db, [c.conversation_id for c in out])
    projects = dict((await db.execute(
        select(ConversationContext.id, ConversationContext.project_id).where(
            ConversationContext.id.in_([c.conversation_id for c in out]),
            ConversationContext.project_id.isnot(None)))).all())
    pinned = set((await db.execute(select(ConversationContext.id).where(       # SB1-2
        ConversationContext.id.in_([c.conversation_id for c in out]), ConversationContext.pinned.is_(True)))).scalars())
    for item in out:
        for key, value in extra.get(item.conversation_id, {}).items():
            setattr(item, key, value)
        if quick:
            item.kind = "quick"                 # Q1: the stored kind wins; describe works out the rest as before
        item.project_id = projects.get(item.conversation_id)
        item.pinned = item.conversation_id in pinned
        # DELETE-BY: v0.1.64 if the iPhone's Quick Ask (Q1c) ships with it, else v0.1.65 (Q1 card, #4; the user, 2026-10-29): the pocket ("Remote") stays only for phones that don't say `quick`.
        if item.conversation_id == phone_reads.REMOTE_ID:
            item.title = phone_reads.REMOTE_TITLE
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


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Purge a conversation's OWN rows across the FK-less `conversation_id` tables.
    Deliberately KEEPS `runs` + `usage_ledger` (audit/diagnosis
    and cost-accounting data must survive conversation deletion, mirroring how audit
    rows survive spawn deletion; so does the permission ledger, `approval_events`, which
    keeps its own 90 days). The conversation's permission grants go with it: they were
    only ever for this conversation.
    Auth-gated (inherited from the router-level require_auth dependency)."""
    deleted: dict[str, int] = {}
    # Injected session — see list_conversations for why. With this endpoint on
    # the module global and the listing on the injection, the two talked to
    # DIFFERENT databases under the shared test client: the delete landed in the
    # user's real one and the listing read a temp one. `get_session` reads the
    # module global at call time, so fixtures that patch AsyncSessionLocal keep
    # working exactly as before.
    for model in (
        ArslanMessage,
        ArslanSummary,
        ConversationEvent,
        ConversationSpawn,
        SpawnPhase,
        DistilledSession,
        PermissionGrant,
    ):
        res = await db.execute(
            delete(model).where(model.conversation_id == conversation_id))
        deleted[model.__tablename__] = res.rowcount or 0
    await db.commit()
    return {"ok": True, "deleted": deleted}


# ── 0.1.58 §6: the model one conversation runs on ─────────────────────────────

from datetime import datetime as _dt  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field  # noqa: E402


class ConversationModelIn(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    config_id: int = Field(ge=1)
    model: str = Field(min_length=1, max_length=200)


@router.get("/conversations/{conversation_id}/model")
async def get_conversation_model(conversation_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    """The model chosen for this conversation, or null = the default (the primary config's model)."""
    from server.db.models import ConversationModel
    row = await db.get(ConversationModel, conversation_id)
    return {"choice": {"config_id": row.config_id, "model": row.model} if row else None}


@router.put("/conversations/{conversation_id}/model")
async def set_conversation_model(conversation_id: str, body: ConversationModelIn,
                                 db: AsyncSession = Depends(get_session)) -> dict:
    """From the next turn on, this conversation runs on that model. Nothing else changes."""
    from server.db.models import ConversationModel, ProviderConfig
    if len(conversation_id) > 100 or not conversation_id.strip():
        raise HTTPException(422, detail={"code": "invalid_conversation_id"})
    if await db.get(ProviderConfig, body.config_id) is None:
        raise HTTPException(404, detail={"code": "provider_config_not_found"})
    model = body.model.strip()
    row = await db.get(ConversationModel, conversation_id)
    if row is None:
        db.add(ConversationModel(conversation_id=conversation_id, config_id=body.config_id, model=model, updated_at=_dt.utcnow()))
    else:
        row.config_id, row.model, row.updated_at = body.config_id, model, _dt.utcnow()
    await db.commit()
    return {"choice": {"config_id": body.config_id, "model": model}}


@router.delete("/conversations/{conversation_id}/model")
async def clear_conversation_model(conversation_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    from server.db.models import ConversationModel
    row = await db.get(ConversationModel, conversation_id)
    if row is not None:
        await db.delete(row)
        await db.commit()
    return {"choice": None}


@router.post("/conversations/{conversation_id}/seen")
async def mark_conversation_seen(conversation_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    """INB4: the window shows this conversation, so its newest message is seen: a reply or a job done there stops reading
    "done, not seen" (phone_reads.describe)."""
    from server.services import conversation_seen
    if len(conversation_id) > 100 or not conversation_id.strip():
        raise HTTPException(422, detail={"code": "invalid_conversation_id"})
    return {"seen_message_id": await conversation_seen.mark(db, conversation_id)}
