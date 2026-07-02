"""Read-only Run replay + evaluation endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.session import get_session
from server.db.models import Run, RunEvaluation, RunStep
from server.schemas import (
    RunDetailOut,
    RunEvaluationOut,
    RunListItemOut,
    RunOut,
    RunSpawnSummaryOut,
    RunStepOut,
    RunSummaryOut,
    RunTrendPointOut,
)

router = APIRouter(dependencies=[Depends(require_auth)])

# Judge dimensions, in display order (mirrors the frontend DIMENSION_LABELS).
DIMENSIONS = ("routing", "fabrication", "identity", "completion")

PASS_THRESHOLD = 7.0


@router.get("/runs", response_model=list[RunListItemOut])
async def list_runs(
    spawn_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
) -> list[RunListItemOut]:
    q = select(Run).order_by(Run.id.desc()).limit(limit)
    if spawn_id is not None:
        q = q.where(Run.spawn_id == spawn_id)
    rows = (await db.execute(q)).scalars().all()
    return [
        RunListItemOut(
            id=r.id, spawn_name=r.spawn_name, status=r.status,
            overall_score=r.overall_score, overall_badge=r.overall_badge,
            total_ms=r.total_ms, user_message=r.user_message,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]


# NOTE: must stay registered BEFORE /runs/{run_id}, or FastAPI tries to parse
# "summary" as an int path param (422).
@router.get("/runs/summary", response_model=RunSummaryOut)
async def runs_summary(db: AsyncSession = Depends(get_session)) -> RunSummaryOut:
    scored = (Run.status == "scored", Run.overall_score.isnot(None))

    scored_count, avg_score = (await db.execute(
        select(func.count(Run.id), func.avg(Run.overall_score)).where(*scored)
    )).one()
    pass_count = (await db.execute(
        select(func.count(Run.id)).where(*scored, Run.overall_score >= PASS_THRESHOLD)
    )).scalar_one()
    pass_rate = round(pass_count / scored_count * 100) if scored_count else None

    dim_rows = (await db.execute(
        select(RunEvaluation.dimension, func.avg(RunEvaluation.score))
        .join(Run, Run.id == RunEvaluation.run_id)
        .where(*scored)
        .group_by(RunEvaluation.dimension)
    )).all()
    dimension_averages: dict[str, float | None] = {d: None for d in DIMENSIONS}
    for dim, avg in dim_rows:
        if dim in dimension_averages and avg is not None:
            dimension_averages[dim] = round(float(avg), 2)

    spawn_rows = (await db.execute(
        select(
            Run.spawn_name,
            func.count(Run.id),
            func.avg(Run.overall_score),
            func.sum(case((Run.overall_score >= PASS_THRESHOLD, 1), else_=0)),
        )
        .where(*scored, Run.spawn_name.isnot(None))
        .group_by(Run.spawn_name)
        .order_by(func.count(Run.id).desc())
    )).all()
    per_spawn = [
        RunSpawnSummaryOut(
            spawn_name=name,
            scored_count=cnt,
            avg_score=round(float(avg), 2) if avg is not None else None,
            pass_rate=round((passed or 0) / cnt * 100) if cnt else None,
        )
        for name, cnt, avg, passed in spawn_rows
    ]

    recent_rows = (await db.execute(
        select(Run.id, Run.overall_score, Run.created_at)
        .order_by(Run.id.desc())
        .limit(50)
    )).all()
    recent = [
        RunTrendPointOut(
            id=rid, overall_score=score,
            created_at=created.isoformat() if created else None,
        )
        for rid, score, created in reversed(recent_rows)
    ]

    return RunSummaryOut(
        scored_count=scored_count,
        avg_score=round(float(avg_score), 2) if avg_score is not None else None,
        pass_rate=pass_rate,
        dimension_averages=dimension_averages,
        per_spawn=per_spawn,
        recent=recent,
    )


@router.get("/runs/{run_id}", response_model=RunDetailOut)
async def get_run(run_id: int, db: AsyncSession = Depends(get_session)) -> RunDetailOut:
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    steps = (await db.execute(
        select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.seq)
    )).scalars().all()
    evals = (await db.execute(
        select(RunEvaluation).where(RunEvaluation.run_id == run_id)
    )).scalars().all()

    return RunDetailOut(
        run=RunOut(
            id=run.id, conversation_id=run.conversation_id, spawn_id=run.spawn_id,
            spawn_name=run.spawn_name, user_message=run.user_message, total_ms=run.total_ms,
            task_tokens=run.task_tokens, status=run.status,
            overall_score=run.overall_score, overall_badge=run.overall_badge,
        ),
        steps=[RunStepOut(seq=s.seq, kind=s.kind, ref=s.ref or {}, detail=s.detail or {},
                          duration_ms=s.duration_ms) for s in steps],
        evaluations=[RunEvaluationOut(dimension=e.dimension, status=e.status,
                                      score=e.score, comment=e.comment) for e in evals],
    )
