"""Privacy retention for run debug detail. Clears ONLY the SENSITIVE + BULKY fields
(system_prompt, injected_kb, injected_kb_sources, per-step args_full/result_raw) while
keeping stats (scores, timings, summaries). Never deletes a run row. Shared by the boot
sweep and the manual redact endpoints. Idempotent."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import Run, RunStep

_BULKY_STEP_KEYS = ("args_full", "result_raw")


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
        runs = (await db.execute(select(Run).where(Run.created_at < cutoff))).scalars().all()
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
