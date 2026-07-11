"""Boot-time reaper (E1): re-enqueue judge scoring for stuck runs.

A run left in 'recorded' or 'score_failed' for more than STUCK_AFTER means the
process died around scoring (or the judge errored) and the fire-and-forget task
never came back — without this, those runs silently rot and never become corpus.
Called once from the app lifespan; best-effort (a failure never blocks boot).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import Run

logger = logging.getLogger(__name__)

STUCK_AFTER = timedelta(minutes=10)
_STUCK_STATUSES = ("recorded", "score_failed")


async def _reaper_candidates() -> list[int]:
    """Run ids stuck in a scorable status for longer than STUCK_AFTER.

    E2: the query filters `kind == 'live'` so replay runs can never be re-enqueued (their
    terminal status 'replayed' already never matches the status filter — the kind filter
    makes it structural, even for a replay row left mid-flight in a scorable status).
    """
    cutoff = datetime.utcnow() - STUCK_AFTER
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Run.id)
            .where(Run.status.in_(_STUCK_STATUSES), Run.created_at < cutoff,
                   Run.kind == "live")
            .order_by(Run.id)
        )
        return list(rows.scalars().all())


async def mark_interrupted_runs() -> int:
    """S3-M1 boot sweep: a 'recording' row at boot is by definition orphaned —
    runs never survive a process restart (the run registry is process-local), so
    mark them 'interrupted' instead of letting them rot as recording-forever
    zombies. Live runs only (a replay row is the gate's problem).
    Assumes exclusive DB ownership (single process — same assumption as run_registry)."""
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Run).where(Run.status == "recording", Run.kind == "live"))
        runs = list(rows.scalars().all())
        for run in runs:
            run.status = "interrupted"
            run.ended_at = run.ended_at or datetime.utcnow()
        await db.commit()
    if runs:
        logger.info("run reaper: marked %d orphaned recording run(s) interrupted", len(runs))
    return len(runs)


async def reap_stuck_runs() -> int:
    """Re-enqueue judge scoring for every stuck run; returns how many."""
    from server.services import run_recorder

    ids = await _reaper_candidates()
    for run_id in ids:
        # Attribute access at call time so the test seam (module-level
        # run_recorder.schedule_scoring indirection) keeps working.
        run_recorder.schedule_scoring(run_id)
    if ids:
        logger.info("run reaper: re-enqueued scoring for %d stuck run(s)", len(ids))
    return len(ids)
