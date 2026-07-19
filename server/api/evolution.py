"""Evolution stats + feedback submission endpoints."""
from __future__ import annotations

import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.models import EvolutionAttempt, EvolutionProposal, Feedback, Run, Spawn
from server.db.session import get_session
from server.schemas import (
    BaselineDeclareOut,
    BaselineStatusOut,
    ConfirmProposalOut,
    EstimateOut,
    EvolutionOut,
    EvolveEnqueuedOut,
    EvolveRequest,
    FeedbackIn,
    ProposalDetailOut,
    ProposalListItemOut,
    RefreshProposalOut,
    RollbackProposalOut,
    SpawnDiagnosisOut,
)
from server.services import (
    evolution_diagnostics,
    evolution_estimate,
    evolution_loop,
    evolution_service,
    evolution_watcher,
    settings_service,
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
    """Cost estimate for ONE evolution attempt on this spawn.

    NOT a reliable lower bound despite the `lower_bound` field — see
    evolution_estimate.py's docstring. I corrected that module and the schema in the
    previous commit and left this one saying "honest lower-bound", which is the same
    half-fix pattern as shipping an ISO separator without the UTC designator.
    """
    est = await evolution_estimate.estimate(session, spawn_id)
    return EstimateOut(**est)


#: Outcomes after which re-running the SAME corpus is near-certain to repeat itself, so a
#: click that would do it needs an explicit acknowledgement.
#:
#: 🔴 `skipped_structural` is deliberately ABSENT. The eligibility panel's own copy tells
#: the user to click evolve in exactly that state so the gate can mint the synthetic
#: holdout top-up; refusing there would make the app contradict its own instructions.
#: `error` is absent too — it says nothing about the corpus, and retrying once a dead
#: adapter is repaired is the correct move, not something to make the user force.
_REPEAT_WARN_OUTCOMES = ("failed",)


@router.post(
    "/spawns/{spawn_id}/evolve", status_code=status.HTTP_202_ACCEPTED,
    response_model=EvolveEnqueuedOut,
)
async def evolve_spawn(
    spawn_id: int,
    body: EvolveRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> EvolveEnqueuedOut:
    """Manual trigger — a BACKGROUND job (202). The old sync run replayed every pair +
    judge inline and was guaranteed to time out. Creates an EvolutionAttempt and enqueues
    a supervised runner; returns immediately. Bypasses the run-count threshold but still
    respects the budget cap + concurrency=1.

    SPEND GATE (批1 P5). If nothing new has been recorded since an attempt that already
    failed on quality, this click would re-run the identical corpus and near-certainly
    repeat the identical verdict. Spending is the executing side, so it is FAIL-CLOSED:
    the refusal is a 409 whose detail carries everything the confirmation dialog needs —
    the frontend renders the backend's facts rather than inventing an explanation — and
    only an explicit `force: true` proceeds. A body-less legacy call therefore has no
    `force` and IS gated; being an old caller is not an exemption from spending money.
    """
    # Concurrency FIRST. If an attempt is already running for this spawn, the click
    # enqueues nothing and spends nothing, so warning about spend would describe a
    # decision that is not being made. (Cheap membership test, and it also spares the
    # gate's corpus scan.)
    if spawn_id in evolution_watcher._running_spawns:
        return EvolveEnqueuedOut(attempt_id=None)

    force = bool(body.force) if body else False
    if not force:
        refusal = await _repeat_spend_refusal(session, spawn_id)
        if refusal is not None:
            raise HTTPException(status_code=409, detail=refusal)

    attempt_id = await evolution_watcher.enqueue_attempt(spawn_id, manual=True)
    return EvolveEnqueuedOut(attempt_id=attempt_id)


async def _repeat_spend_refusal(session, spawn_id: int) -> dict | None:
    """The 409 payload, or None when the click is fine to run.

    Both facts come from the SAME attempt row on purpose: reporting `last_reason` from one
    attempt and `new_runs_since` measured from another would produce a dialog that
    describes a state the spawn was never in.
    """
    last = (await session.execute(
        select(EvolutionAttempt)
        .where(EvolutionAttempt.spawn_id == spawn_id,
               EvolutionAttempt.outcome.is_not(None))
        .order_by(EvolutionAttempt.id.desc())
        .limit(1)
    )).scalars().first()
    if last is None or last.outcome not in _REPEAT_WARN_OUTCOMES:
        return None

    new_runs = await evolution_watcher._new_replayable_run_count(
        session, spawn_id, last.started_at)
    if new_runs > 0:
        return None

    est = await evolution_estimate.estimate(session, spawn_id)
    return {
        "code": "same_corpus_as_failed_attempt",
        "last_attempt_id": last.id,
        "last_outcome": last.outcome,
        "last_reason": last.reason or "",
        "new_runs_since": new_runs,
        "est_tokens": est.get("est_tokens"),
        # 🔴 NOT a ceiling and NOT a reliable floor either — the estimator applies the
        # optimizer's per-pair multiplier to the WHOLE corpus while the optimizer only
        # ever sees <=8 val pairs, so it overshoots more the bigger the corpus gets.
        # Registered as its own project; do not present this number as a forecast.
        "est_is_lower_bound": bool(est.get("lower_bound")),
    }


@router.post("/evolution/baseline/declare", response_model=BaselineDeclareOut)
async def declare_baseline(
    session: AsyncSession = Depends(get_session),
) -> BaselineDeclareOut:
    """E9 step 1: the developer declares NOW as the clean-corpus start. From here on
    build_corpus/replay_set floor real runs at this timestamp, so S2 dev/testing runs (which
    are epoch=1 too, since E1..E8 landed on this branch) never pollute the corpus (audit #12)."""
    now = datetime.utcnow()
    await settings_service.set_baseline_started_at(session, now)
    return BaselineDeclareOut(baseline_started_at=now.isoformat())


@router.get("/evolution/baseline", response_model=BaselineStatusOut)
async def get_baseline(
    session: AsyncSession = Depends(get_session),
) -> BaselineStatusOut:
    """Report the declared clean-corpus start and how many clean-corpus (kind='live',
    epoch>=1, created_at>=baseline) runs have arrived since — so the developer can watch the
    real corpus accumulate before the first real promotion."""
    baseline = await settings_service.get_baseline_started_at(session)
    count = 0
    if baseline is not None:
        count = (await session.execute(
            select(func.count()).select_from(Run).where(
                Run.kind == "live", Run.epoch >= 1, Run.created_at >= baseline)
        )).scalar() or 0
    return BaselineStatusOut(
        baseline_started_at=baseline.isoformat() if baseline else None,
        epoch1_runs_after=count,
    )


@router.get("/spawns/{spawn_id}/evolution/diagnosis", response_model=SpawnDiagnosisOut)
async def get_evolution_diagnosis(
    spawn_id: int,
    session: AsyncSession = Depends(get_session),
) -> SpawnDiagnosisOut:
    """Read-only evolution eligibility diagnosis for one spawn — the data behind the inbox's
    'why no proposals yet' panel. Reuses the shared evolution_diagnostics service (one source of
    truth with the CLI); SELECT-only within the request session (build_corpus mint defaults to
    False, so inspecting a spawn never mints synthetic tasks or spends tokens)."""
    spawn = await spawn_service.get_spawn(session, spawn_id)
    if spawn is None:
        raise HTTPException(status_code=404, detail="spawn not found")
    d = await evolution_diagnostics.diagnose_spawn(session, spawn)
    return SpawnDiagnosisOut(
        spawn_id=spawn.id, spawn_name=spawn.name, generation_level=d["generation_level"],
        total_scored=d["total_scored"], replayable=d["replayable"],
        non_replayable=d["non_replayable"], offending_tools=d["offending_tools"],
        baseline_started_at=d["baseline"].isoformat() if d["baseline"] else None,
        scored_ge_baseline=d["scored_ge_baseline"], corpus_total=d["corpus_total"],
        holdout_ceiling=d["holdout_ceiling"], real_holdout=d["real_holdout"],
        effective_holdout=d["effective_holdout"], propose_count=d["propose_count"],
        corpus_excluded=d["corpus_excluded"], min_holdout_n=d["min_holdout_n"],
        consecutive_fails=d["consec_fails"], threshold=d["threshold"],
        count_since_last_attempt=d["count_since"], auto_eligible=d["auto_eligible"],
        open_proposals=d["open_props"], auto_on=d["auto_on"],
        max_est_tokens=d["max_est_tokens"], last_attempts=d["last_attempts"],
        verdict_code=d["verdict_code"], verdict_params=d["verdict_params"])


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
