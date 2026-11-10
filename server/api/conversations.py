"""Conversation-scoped recap — runs + growth events merged into one timeline."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
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
    out: they have a list of their own on the phone and never reach the sidebar. SUB5d: sub-sessions are in it, each
    with its `parent_id`, so the window's sidebar builds the tree; every phone route still leaves them out (SUB2)."""
    return await conversation_list(db, sub=True)


async def conversation_list(db: AsyncSession, *, quick: bool = False, sub: bool = False) -> list[ConversationListItem]:
    """Every conversation that has messages, most recently active first: the ordinary ones, or with
    `quick` only the stored quick questions (Q1, migration 0071). With `sub` (the window's list only, SUB5d) the
    sub-sessions too.

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
    out = [c for c in out if phone_ids.in_list(c.conversation_id, kinds.get(c.conversation_id), quick=quick)
           or (sub and not quick and kinds.get(c.conversation_id) == "sub")]
    # What each one is and how it stands — the sidebar's glyphs, the phone's task list. The retired pocket
    # (Q1 card, #4) is an ordinary conversation here, named after its first message; the Bridge keeps it from phones.
    from server.services import phone_reads
    extra = await phone_reads.describe(db, [c.conversation_id for c in out])
    projects = dict((await db.execute(
        select(ConversationContext.id, ConversationContext.project_id).where(
            ConversationContext.id.in_([c.conversation_id for c in out]),
            ConversationContext.project_id.isnot(None)))).all())
    pinned = set((await db.execute(select(ConversationContext.id).where(       # SB1-2
        ConversationContext.id.in_([c.conversation_id for c in out]), ConversationContext.pinned.is_(True)))).scalars())
    parents = dict((await db.execute(select(ConversationContext.id, ConversationContext.parent_id).where(
        ConversationContext.id.in_([c.conversation_id for c in out if kinds.get(c.conversation_id) == "sub"]))))
        .all()) if sub else {}
    from server.services import background_jobs, sub_sessions
    # SUB5d: a sub-session whose job has finished but whose report isn't delivered yet still counts as at work (the
    # delete refuses it with 409 `sub_sessions_running`), so its row reads working, marked `reporting`.
    reporting = {job.conversation_id for job in background_jobs.unreported()} if sub else set()
    for item in out:
        for key, value in extra.get(item.conversation_id, {}).items():
            setattr(item, key, value)
        if quick:
            item.kind = "quick"                 # Q1: the stored kind wins; describe works out the rest as before
        item.project_id = projects.get(item.conversation_id)
        item.pinned = item.conversation_id in pinned
        item.parent_id = parents.get(item.conversation_id)
        # SUB5d: a sub-session's card is asked in its parent's conversation, so the island lists the parent; the
        # sub-session's own row reads waiting while one of its cards waits (sub_sessions.waiting_on_user).
        if item.parent_id and sub_sessions._waiting.get(item.conversation_id):
            item.state, item.waiting_on = "waiting", "card"
        elif item.parent_id and item.state not in ("working", "waiting") and item.conversation_id in reporting:
            item.state, item.reporting = "working", True
    return out


@router.get("/conversations/{conversation_id}/sub-sessions/spend")
async def sub_session_spend(conversation_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    """SUB5d: what the tree this conversation is in has spent, as its limit counts it (`sub_sessions.check_tree_spend`:
    every sub-session under the commander and its summary turns, not the commander's own turns). The window reads the
    limit itself from the per-task dollar cap in Settings."""
    from server.db.companion_models import ConversationContext
    from server.services import sub_sessions
    row = await db.get(ConversationContext, conversation_id)
    if row is None or row.kind == "deleted":      # one in no tree has no row (a commander gets one); SUB5a's tombstone
        raise HTTPException(404, detail="not_found")
    root = await sub_sessions.root_of(db, conversation_id)
    spent = await sub_sessions.tree_spend(db, (await sub_sessions.tree(db, root))[1:], summaries_in=root)
    return {"spent_usd": round(spent, 4)}


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
    sub_sessions: Literal["delete", "keep"] | None = None,
    sub_session: bool = False,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Purge a conversation's OWN rows across the FK-less `conversation_id` tables.
    Deliberately KEEPS `runs` + `usage_ledger` (audit/diagnosis
    and cost-accounting data must survive conversation deletion, mirroring how audit
    rows survive spawn deletion; so does the permission ledger, `approval_events`, which
    keeps its own 90 days). The conversation's permission grants go with it: they were
    only ever for this conversation.
    Auth-gated (inherited from the router-level require_auth dependency).

    SUB5a: its context row is left a tombstone in the same commit, with nothing of its settings (a child read them
    through it), and the id is refused from then on, also after a restart (`sub_sessions.tombstone`, `is_deleted`).
    Before that, its own jobs are stopped and it is marked deleted in this process (`sub_sessions.before_delete`,
    `sub_sessions.deleted`). A conversation
    with sub-sessions needs `sub_sessions`: "delete" takes its whole tree, "keep" makes its own sub-sessions
    top-level chats (`sub_sessions.before_delete`); 409 while one is at work. A sub-session is deleted only when
    named as one (`sub_session=true`): the phone's `conversation.delete` names none, and gets its not-found."""
    from server.db.companion_models import ConversationContext
    from server.services import sub_sessions as subs
    try:
        ids, kept = await subs.before_delete(db, conversation_id, choice=sub_sessions, as_sub_session=sub_session)
    except subs.SubSessionError as exc:
        if exc.code == "not_found":
            raise HTTPException(404, detail="not_found") from None
        raise HTTPException(409 if exc.code == "sub_sessions_running" else 422,
                            detail={"code": exc.code, **exc.extra}) from None
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
            delete(model).where(model.conversation_id.in_(ids)))
        deleted[model.__tablename__] = res.rowcount or 0
    # Not removed: left a tombstone, which refuses the id from then on, also after a restart (`subs.tombstone`).
    deleted[ConversationContext.__tablename__] = await subs.tombstone(db, ids)
    await db.commit()
    return {"ok": True, "deleted": deleted, **({"kept": kept} if kept else {})}


# ── 0.1.58 §6: the model one conversation runs on ─────────────────────────────

from datetime import datetime as _dt  # noqa: E402

from pydantic import BaseModel, ConfigDict, Field  # noqa: E402


class ConversationModelIn(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    config_id: int = Field(ge=1)
    model: str = Field(min_length=1, max_length=200)


@router.get("/conversations/{conversation_id}/model")
async def get_conversation_model(conversation_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    """The model chosen for this conversation (null = the default), and `effective`: what its next text turn
    really runs on (llm_factory.effective_choice), which the chip shows."""
    from server.db.models import ConversationModel
    from server.services import llm_factory
    row = await db.get(ConversationModel, conversation_id)
    return {"choice": {"config_id": row.config_id, "model": row.model} if row else None,
            "effective": await llm_factory.effective_choice(db, conversation_id)}


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
    if not model:          # "  " passes min_length before the strip (#691 review)
        raise HTTPException(422, detail={"code": "invalid_model"})
    row = await db.get(ConversationModel, conversation_id)
    if row is None:
        db.add(ConversationModel(conversation_id=conversation_id, config_id=body.config_id, model=model, updated_at=_dt.utcnow()))
    else:
        row.config_id, row.model, row.updated_at = body.config_id, model, _dt.utcnow()
    await db.commit()
    from server.services import llm_factory
    return {"choice": {"config_id": body.config_id, "model": model},
            "effective": await llm_factory.effective_choice(db, conversation_id)}


@router.delete("/conversations/{conversation_id}/model")
async def clear_conversation_model(conversation_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    from server.db.models import ConversationModel
    from server.services import llm_factory
    row = await db.get(ConversationModel, conversation_id)
    if row is not None:
        await db.delete(row)
        await db.commit()
    return {"choice": None, "effective": await llm_factory.effective_choice(db, conversation_id)}


@router.post("/conversations/{conversation_id}/seen")
async def mark_conversation_seen(conversation_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    """INB4: the window shows this conversation, so its newest message is seen: a reply or a job done there stops reading
    "done, not seen" (phone_reads.describe)."""
    from server.services import conversation_seen
    if await db.scalar(select(ArslanMessage.id).where(ArslanMessage.conversation_id == conversation_id).limit(1)) is None:
        raise HTTPException(404, detail={"code": "conversation_not_found"})
    return {"seen_message_id": await conversation_seen.mark(db, conversation_id)}
