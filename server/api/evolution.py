"""Evolution stats + feedback submission endpoints."""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.models import EvolutionAttempt, EvolutionProposal, Feedback, Spawn
from server.db.session import get_session
from server.schemas import (
    ConfirmProposalOut,
    EstimateOut,
    EvolutionOut,
    EvolveEnqueuedOut,
    FeedbackIn,
    ProposalDetailOut,
    ProposalListItemOut,
    RefreshProposalOut,
    RollbackProposalOut,
)
from server.services import (
    evolution_estimate,
    evolution_loop,
    evolution_service,
    evolution_watcher,
    skill_doc,
    spawn_service,
)


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/spawns/{spawn_id}/evolution", response_model=EvolutionOut)
async def get_evolution(
    spawn_id: int, session: AsyncSession = Depends(get_session)
) -> EvolutionOut:
    spawn = await spawn_service.get_spawn(session, spawn_id)
    if spawn is None:
        raise HTTPException(status_code=404, detail="Spawn not found")
    stats = evolution_service.get_stats(spawn.name)
    return EvolutionOut(**stats)


@router.post(
    "/spawns/{spawn_id}/feedback", status_code=status.HTTP_201_CREATED
)
async def submit_feedback(
    spawn_id: int,
    body: FeedbackIn,
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    spawn = await spawn_service.get_spawn(session, spawn_id)
    if spawn is None:
        raise HTTPException(status_code=404, detail="Spawn not found")
    evolution_service.record_feedback(
        spawn.name,
        session_id=f"spawn-{spawn_id}",
        user_input="",
        agent_output="",
        user_action=body.user_action,
        edits=body.edits,
    )
    session.add(
        Feedback(
            spawn_id=spawn_id,
            session_id=f"spawn-{spawn_id}",
            message_id=body.message_id,
            user_action=body.user_action,
            edits=body.edits,
            quality_signal=evolution_service.quality_signal_for(body.user_action),
        )
    )
    await session.commit()
    return {"ok": True}


@router.get("/spawns/{spawn_id}/evolve/estimate", response_model=EstimateOut)
async def evolve_estimate(
    spawn_id: int, session: AsyncSession = Depends(get_session)
) -> EstimateOut:
    """Honest lower-bound cost estimate for ONE evolution attempt on this spawn."""
    est = await evolution_estimate.estimate(session, spawn_id)
    return EstimateOut(**est)


@router.post(
    "/spawns/{spawn_id}/evolve", status_code=status.HTTP_202_ACCEPTED,
    response_model=EvolveEnqueuedOut,
)
async def evolve_spawn(spawn_id: int) -> EvolveEnqueuedOut:
    """Manual trigger — now a BACKGROUND job (202). The old sync run replayed every pair +
    judge inline and was guaranteed to time out. Creates an EvolutionAttempt and enqueues a
    supervised runner; returns immediately. Bypasses the run-count threshold but still
    respects the budget cap + concurrency=1."""
    attempt_id = await evolution_watcher.enqueue_attempt(spawn_id, manual=True)
    return EvolveEnqueuedOut(attempt_id=attempt_id)


@router.get("/evolution/proposals", response_model=list[ProposalListItemOut])
async def list_proposals(
    status: str | None = None, session: AsyncSession = Depends(get_session)
) -> list[ProposalListItemOut]:
    """The evolution inbox backend: proposals + their split evidence deltas/tier/status."""
    q = select(EvolutionProposal).order_by(EvolutionProposal.id.desc())
    if status:
        q = q.where(EvolutionProposal.status == status)
    rows = (await session.execute(q)).scalars().all()
    out: list[ProposalListItemOut] = []
    for p in rows:
        ev = p.evidence or {}
        out.append(ProposalListItemOut(
            id=p.id, spawn_id=p.spawn_id, status=p.status, gate_passed=bool(p.gate_passed),
            base_prompt_sha=p.base_prompt_sha,
            real_delta=ev.get("real_delta"), synthetic_delta=ev.get("synthetic_delta"),
            evidence_tier=ev.get("evidence_tier"), flags=list(ev.get("flags", []) or []),
            created_at=p.created_at.isoformat() if p.created_at else None,
            promoted_at=p.promoted_at.isoformat() if p.promoted_at else None,
        ))
    return out


@router.get("/evolution/proposals/{proposal_id}", response_model=ProposalDetailOut)
async def get_proposal(
    proposal_id: int, session: AsyncSession = Depends(get_session)
) -> ProposalDetailOut:
    """The E7 promotion-card payload: full holdout-only evidence (pairs, dual deltas, tier),
    the candidate prompt, and the honest base prompt to diff against. `base_prompt` is the
    spawn's CURRENT canonicalized system_prompt; `is_stale` is True when it has drifted from the
    gate's baseline (base_prompt_sha) — the card diffs against the live base and warns. estimate/
    actual are pulled from the proposal's linked EvolutionAttempt when present."""
    prop = await session.get(EvolutionProposal, proposal_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    spawn = await session.get(Spawn, prop.spawn_id)

    base_prompt: str | None = None
    is_stale = False
    generation_level: int | None = None
    spawn_name: str | None = None
    if spawn is not None:
        # Canonicalize exactly as the gate/refresh path does so the sha comparison and the
        # rendered diff agree with what the gate actually ran against (evolution_loop).
        base_prompt = skill_doc.apply_edits(spawn.system_prompt or "", [])
        generation_level = spawn.generation_level
        spawn_name = spawn.name
        if prop.base_prompt_sha and _sha(base_prompt) != prop.base_prompt_sha:
            is_stale = True

    attempt = (await session.execute(
        select(EvolutionAttempt)
        .where(EvolutionAttempt.proposal_id == proposal_id)
        .order_by(EvolutionAttempt.id.desc())
        .limit(1)
    )).scalar_one_or_none()

    return ProposalDetailOut(
        id=prop.id, spawn_id=prop.spawn_id, spawn_name=spawn_name, status=prop.status,
        gate_passed=bool(prop.gate_passed), generation_level=generation_level,
        base_prompt_sha=prop.base_prompt_sha, base_prompt=base_prompt,
        candidate_prompt=prop.candidate_prompt, is_stale=is_stale,
        evidence=dict(prop.evidence or {}),
        estimate=(dict(attempt.estimate) if attempt and attempt.estimate else None),
        actual=(dict(attempt.actual) if attempt and attempt.actual else None),
        created_at=prop.created_at.isoformat() if prop.created_at else None,
        promoted_at=prop.promoted_at.isoformat() if prop.promoted_at else None,
    )


@router.post("/evolution/proposals/{proposal_id}/refresh", response_model=RefreshProposalOut)
async def refresh_proposal(
    proposal_id: int, session: AsyncSession = Depends(get_session)
) -> RefreshProposalOut:
    """Living-proposal refresh: accumulate new holdout pairs, recompute the verdict, and
    flip gate_passed / flag 'no_longer_passing' if the evidence weakened (status stays open).
    A drifted base prompt marks the proposal 'stale'."""
    result = await evolution_loop.refresh_proposal(session, proposal_id)
    return RefreshProposalOut(**result)


@router.post("/evolution/proposals/{proposal_id}/confirm", response_model=ConfirmProposalOut)
async def confirm_proposal(proposal_id: int) -> ConfirmProposalOut:
    result = await evolution_loop.confirm_proposal(proposal_id)
    # A stale proposal (base prompt drifted from the gate's baseline) must be re-gated before
    # promotion — reject with 409 rather than silently promoting against a moved baseline.
    if not result.get("ok") and "stale" in (result.get("reason") or ""):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="proposal is stale; re-run the gate before promoting")
    return ConfirmProposalOut(**result)


@router.post("/evolution/proposals/{proposal_id}/reject", response_model=ConfirmProposalOut)
async def reject_proposal(
    proposal_id: int, session: AsyncSession = Depends(get_session)
) -> ConfirmProposalOut:
    """Human dismiss: mark the proposal 'rejected'. Refuses a promoted proposal (409) — a
    promoted candidate is rolled back, not rejected."""
    result = await evolution_loop.reject_proposal(session, proposal_id)
    if not result.get("ok") and "promoted" in (result.get("reason") or ""):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="proposal is already promoted; roll it back instead")
    return ConfirmProposalOut(**result)


@router.post("/evolution/proposals/{proposal_id}/rollback", response_model=RollbackProposalOut)
async def rollback_proposal(
    proposal_id: int, session: AsyncSession = Depends(get_session)
) -> RollbackProposalOut:
    """Undo a promotion (spec §E7 audit #14): restore the spawn's previous-generation prompt
    from prompt_history and re-open the proposal. Refuses anything not currently promoted (409)."""
    result = await evolution_loop.rollback_proposal(session, proposal_id)
    if not result.get("ok") and "not promoted" in (result.get("reason") or ""):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="proposal is not promoted; nothing to roll back")
    return RollbackProposalOut(**result)
