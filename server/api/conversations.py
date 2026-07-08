"""Conversation-scoped recap — runs + growth events merged into one timeline."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from server.auth import require_auth
from server.schemas import RecapOut

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/conversations/{conversation_id}/recap", response_model=RecapOut)
async def conversation_recap(conversation_id: str) -> RecapOut:
    from server.services import recap_service

    return RecapOut(**await recap_service.get_recap(conversation_id))
