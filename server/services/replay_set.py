"""Build a per-spawn replay set from scored Runs, for offline evaluation.

A replay item = one scored Run's task + the spawn's delivered output + its judge
dimensions. Consumed by the C2 evaluator (re-run candidate config, compare vs baseline).
Read-only over existing tables; no new schema.
"""
from __future__ import annotations

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ArslanMessage, Run, RunEvaluation

_DIMENSIONS = ("fabrication", "identity", "completion")


async def build(spawn_id: int, *, cap: int = 20) -> list[dict]:
    """Return up to `cap` newest scored-Run replay items for `spawn_id`.

    Each item: {run_id, task, baseline_output, baseline_overall, baseline_dims}.
    Items whose delivered output is missing/empty are skipped. No runs → [].
    """
    items: list[dict] = []
    async with db_session.AsyncSessionLocal() as db:
        runs = (await db.execute(
            select(Run)
            # E2: only clean-corpus live runs — replay arms (kind='replay') and pre-baseline
            # rows (epoch=0) are permanently excluded from the evaluation corpus.
            .where(Run.spawn_id == spawn_id, Run.status == "scored",
                   Run.kind == "live", Run.epoch >= 1)
            .order_by(Run.id.desc())
            .limit(cap)
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


async def build_split(spawn_id: int, *, train_cap: int = 12, val_cap: int = 6,
                      min_val: int = 3) -> dict:
    """Split the newest scored-Run replay items into a held-out train/val set.

    Deterministic interleave by position (every 3rd item -> val) so both splits span
    the same time range (no recency skew, no RNG). Returns {"train": [...], "val": [...]}.
    If fewer than `min_val` items would land in val, returns empty splits (insufficient).
    """
    items = await build(spawn_id, cap=train_cap + val_cap)
    train, val = [], []
    for idx, it in enumerate(items):
        (val if idx % 3 == 2 else train).append(it)
    val = val[:val_cap]
    train = train[:train_cap]
    if len(val) < min_val:
        return {"train": [], "val": []}
    return {"train": train, "val": val}
