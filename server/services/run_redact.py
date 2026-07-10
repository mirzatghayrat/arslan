"""Privacy retention for run debug detail. Clears ONLY the SENSITIVE + BULKY fields
(system_prompt, injected_kb, injected_kb_sources, per-step args_full/result_raw) while
keeping stats (scores, timings, summaries). Never deletes a run row. Shared by the boot
sweep and the manual redact endpoints. Idempotent."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import EvolutionProposal, Run, RunStep, SkillCandidate

_BULKY_STEP_KEYS = ("args_full", "result_raw")


def _add_id(ids: set[int], rid) -> None:
    """Add `rid` to the exemption set iff it is a real int run id (bool is not an id)."""
    if isinstance(rid, int) and not isinstance(rid, bool):
        ids.add(rid)


async def _protected_run_ids(db) -> set[int]:
    """Run ids that must survive the retention sweep (S2 E2, audit CRITICAL-6).

    A replay Run cited by a still-live proposal or skill candidate is the two-arm original
    text a promotion card's win-rate traces to — redacting it would sever that traceability.
    The exemption set is the UNION, over every non-'rejected' EvolutionProposal, of BOTH
    `evidence.protected_run_ids` AND every baseline_run_id/candidate_run_id inside
    `evidence.pairs` (refresh_proposal accumulates new pairs there WITHOUT re-listing them in
    protected_run_ids, so the pairs must be swept directly); PLUS the `samples` run ids of
    every non-'rejected' SkillCandidate (whose evidence renders the same PromotionCard).
    Bounded by design (each row holds ≤ 2× its pair count)."""
    ids: set[int] = set()

    rows = (await db.execute(
        select(EvolutionProposal.evidence).where(EvolutionProposal.status != "rejected")
    )).scalars().all()
    for evidence in rows:
        if not isinstance(evidence, dict):
            continue
        for rid in evidence.get("protected_run_ids") or []:
            _add_id(ids, rid)
        for pair in evidence.get("pairs") or []:
            if isinstance(pair, dict):
                _add_id(ids, pair.get("baseline_run_id"))
                _add_id(ids, pair.get("candidate_run_id"))

    srows = (await db.execute(
        select(SkillCandidate.samples).where(SkillCandidate.status != "rejected")
    )).scalars().all()
    for samples in srows:
        for rid in samples or []:
            _add_id(ids, rid)

    return ids


def _scrub_steps(steps: list[RunStep]) -> None:
    for step in steps:
        if step.detail and any(k in step.detail for k in _BULKY_STEP_KEYS):
            # reassign a new dict so SQLAlchemy detects the JSON change
            step.detail = {k: v for k, v in step.detail.items() if k not in _BULKY_STEP_KEYS}


async def redact_run(run_id: int) -> None:
    """Clear sensitive/bulky fields for a single run. No-op if the run doesn't exist. Idempotent."""
    async with db_session.AsyncSessionLocal() as db:
        run = await db.get(Run, run_id)
        if run is None:
            return
        run.system_prompt = None
        run.injected_kb = None
        run.injected_kb_sources = None
        steps = (await db.execute(select(RunStep).where(RunStep.run_id == run_id))).scalars().all()
        _scrub_steps(list(steps))
        await db.commit()


async def redact_all() -> int:
    """Clear sensitive/bulky fields for every run. Returns the number of runs touched."""
    async with db_session.AsyncSessionLocal() as db:
        runs = (await db.execute(select(Run))).scalars().all()
        for run in runs:
            run.system_prompt = None
            run.injected_kb = None
            run.injected_kb_sources = None
        steps = (await db.execute(select(RunStep))).scalars().all()
        _scrub_steps(list(steps))
        await db.commit()
        return len(runs)


async def sweep(retention_days: int) -> int:
    """Redact runs older than *retention_days*. retention_days <= 0 disables the sweep
    (returns 0 without touching anything). Returns the number of runs redacted."""
    if not retention_days or retention_days <= 0:
        return 0
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    async with db_session.AsyncSessionLocal() as db:
        protected = await _protected_run_ids(db)
        runs = [
            r for r in (await db.execute(select(Run).where(Run.created_at < cutoff))).scalars().all()
            if r.id not in protected  # E2: exempt replay runs cited by a non-rejected proposal
        ]
        ids = [r.id for r in runs]
        for run in runs:
            run.system_prompt = None
            run.injected_kb = None
            run.injected_kb_sources = None
        if ids:
            steps = (await db.execute(select(RunStep).where(RunStep.run_id.in_(ids)))).scalars().all()
            _scrub_steps(list(steps))
        await db.commit()
        return len(runs)
