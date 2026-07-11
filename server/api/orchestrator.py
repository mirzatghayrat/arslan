"""Orchestrator REST endpoints (non-WebSocket)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from server.auth import require_auth
from server.schemas import TitleIn, TitleOut
from server.services.titler import generate_title

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/orchestrator/title", response_model=TitleOut)
async def title_conversation(body: TitleIn) -> TitleOut:
    """Generate a short title for a conversation from its first exchange."""
    title = await generate_title(body.first_message, body.first_reply,
                                 conversation_id=body.conversation_id)
    return TitleOut(title=title)
