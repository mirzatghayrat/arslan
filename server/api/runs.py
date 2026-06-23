"""Read-only Run replay + evaluation endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.session import get_session
from server.db.models import Run, RunEvaluation, RunStep
from server.schemas import RunDetailOut, RunEvaluationOut, RunOut, RunStepOut

router = APIRouter(dependencies=[Depends(require_auth)])


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
