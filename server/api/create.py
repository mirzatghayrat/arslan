"""Manual NL spawn creation endpoints: NL->draft and create-from-draft."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.session import get_session
from server.schemas import DraftIn, EquipmentOut, SpawnCreateIn, SpawnDetailOut
from server.services import spawn_drafter, spawn_service

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/spawns/draft")
async def draft_spawn(body: DraftIn) -> dict[str, Any]:
    return await spawn_drafter.draft_from_text(body.description)


@router.post("/spawns", response_model=SpawnDetailOut, status_code=201)
async def create_spawn(
    body: SpawnCreateIn, session: AsyncSession = Depends(get_session)
) -> SpawnDetailOut:
    # Build a draft dict from the body, including optional explicit equipment.
    draft = {
        "name": body.name,
        "domain": body.domain,
        "capabilities": body.capabilities,
        "seed_refs": body.seed_refs,
        "persona_role": body.persona_role,
        "persona_tone": body.persona_tone,
    }
    if body.equipment is not None:
        draft["equipment"] = body.equipment

    spawn_id, spawn_name, equipment, intro = await spawn_service.create_from_draft(draft)

    # Fetch full detail (including the persisted intro message) using the request session.
    detail = await spawn_service.get_detail(session, spawn_id)
    assert detail is not None

    # Attach equipment directly from create_from_draft's result (already resolved).
    detail.equipment = EquipmentOut.from_dict(equipment)
    return detail

