"""Evolution stats + feedback submission endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.models import Feedback
from server.db.session import get_session
from server.schemas import EvolutionOut, FeedbackIn
from server.services import evolution_service, spawn_service

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
