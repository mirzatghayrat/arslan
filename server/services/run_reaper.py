"""Boot-time sweep (S3-M1): mark orphaned 'recording' runs interrupted.

Called once from the app lifespan; best-effort (a failure never blocks boot).
C7c-5a removed the judge re-enqueue (reap_stuck_runs): nothing scores runs any more.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import Run

logger = logging.getLogger(__name__)

# Old kinds whose orphaned 'recording' rows are still swept (nothing creates them now).
_LEGACY_KINDS = ("live", "scheduled")


async def mark_interrupted_runs() -> int:
    """S3-M1 boot sweep: a 'recording' row at boot is by definition orphaned —
    runs never survive a process restart (the run registry is process-local), so
    mark them 'interrupted' instead of letting them rot as recording-forever
    zombies. Live + scheduled runs (a replay row is the gate's problem).
    Assumes exclusive DB ownership (single process — same assumption as run_registry)."""
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Run).where(Run.status == "recording", Run.kind.in_((*_LEGACY_KINDS, "host", "recipe", "recipe_step"))))
        runs = list(rows.scalars().all())
        for run in runs:
            run.status = "interrupted"
            run.ended_at = run.ended_at or datetime.utcnow()
        await db.commit()
    if runs:
        logger.info("run reaper: marked %d orphaned recording run(s) interrupted", len(runs))
    return len(runs)

