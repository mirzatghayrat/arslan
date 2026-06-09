"""Manual NL spawn creation endpoints: NL->draft and create-from-draft."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.session import get_session
from server.schemas import DraftIn, SpawnCreateIn, SpawnDetailOut
from server.services import spawn_drafter, spawn_service

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/spawns/draft")
async def draft_spawn(body: DraftIn) -> dict[str, Any]:
    return await spawn_drafter.draft_from_text(body.description)


@router.post("/spawns", response_model=SpawnDetailOut, status_code=201)
async def create_spawn(
    body: SpawnCreateIn, session: AsyncSession = Depends(get_session)
) -> SpawnDetailOut:
    category, _, subcategory = body.domain.partition(".")
    system_prompt = spawn_service.build_system_prompt(
        {"persona_role": body.persona_role, "persona_tone": body.persona_tone, "domain": body.domain}
    )
    spawn = await spawn_service.create_spawn_unique(
        session,
        name=body.name,
        domain_category=category,
        domain_subcategory=subcategory or None,
        capabilities=body.capabilities,
        persona_role=body.persona_role,
        persona_tone=body.persona_tone,
        system_prompt=system_prompt,
        generation_level=1,
    )
    return spawn_service.to_detail(spawn, [])
