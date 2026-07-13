"""Build a per-spawn replay set from scored Runs, for offline evaluation.

A replay item = one scored Run's task + the spawn's delivered output + its judge
dimensions. Consumed by the C2 evaluator (re-run candidate config, compare vs baseline).
Read-only over existing tables; no new schema.
"""
from __future__ import annotations

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ArslanMessage, Run, RunEvaluation
from server.services import settings_service

_DIMENSIONS = ("fabrication", "identity", "completion")


async def build(spawn_id: int, *, cap: int = 20, db=None) -> list[dict]:
    """Return up to `cap` newest scored-Run replay items for `spawn_id`.

    Each item: {run_id, task, baseline_output, baseline_overall, baseline_dims}.
    Items whose delivered output is missing/empty are skipped. No runs → [].

    Pass an existing `db` (e.g. a read-only request/CLI session) to read within THAT session
    instead of self-opening the global one — the evolution diagnostics service does this so the
    whole diagnosis reads one consistent session. Omit `db` (the default) to self-manage.
    """
    if db is not None:
        return await _collect(db, spawn_id, cap)
    async with db_session.AsyncSessionLocal() as own:
        return await _collect(own, spawn_id, cap)


async def _collect(db, spawn_id: int, cap: int) -> list[dict]:
    items: list[dict] = []
    # E9: additionally floor real runs at the developer-declared clean-corpus start so
    # S2 dev/testing runs (also epoch=1) never enter the corpus (spec §E9 / audit #12).
    baseline = await settings_service.get_baseline_started_at(db)
    q = (
        select(Run)
        # E2: only clean-corpus live runs — replay arms (kind='replay') and pre-baseline
        # rows (epoch=0) are permanently excluded from the evaluation corpus.
        .where(Run.spawn_id == spawn_id, Run.status == "scored",
               Run.kind == "live", Run.epoch >= 1)
    )
    if baseline is not None:
        q = q.where(Run.created_at >= baseline)
    runs = (await db.execute(
        q.order_by(Run.id.desc()).limit(cap)
    )).scalars().all()

    for run in runs:
        msg = (await db.execute(
            select(ArslanMessage).where(
                ArslanMessage.run_id == run.id,
                ArslanMessage.role == "spawn_summary",
            )
        )).scalars().first()
        if msg is None:
            baseline_output = ""
        elif msg.display_content is not None:
            baseline_output = msg.display_content
        else:
            baseline_output = msg.content or ""
        if not baseline_output:
            continue
        evals = (await db.execute(
            select(RunEvaluation).where(RunEvaluation.run_id == run.id)
        )).scalars().all()
        baseline_dims = {
            e.dimension: {"status": e.status, "score": e.score}
            for e in evals if e.dimension in _DIMENSIONS
        }
        items.append({
            "run_id": run.id,
            "task": run.user_message,
            "baseline_output": baseline_output,
            "baseline_overall": run.overall_score,
            "baseline_dims": baseline_dims,
        })
    return items
