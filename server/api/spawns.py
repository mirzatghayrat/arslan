"""What is left of the spawn REST endpoints. DELETE-BY: v0.1.64, with C7c-4 (the equip popover, the release check's
login probe). C7c-3b removed the preferences routes: expert-scope memory entries are deleted through
DELETE /memory/entries/{id}, which syncs the deletion ledger in `memory_repository.repository()`."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.session import get_session
from server.schemas import (
    EquipmentOut,
    EquipmentUpdateIn,
    SpawnDetailOut,
    SpawnOut,
)
from server.services import spawn_service

router = APIRouter(dependencies=[Depends(require_auth)])


async def _attach_equipment(
    out: SpawnOut | SpawnDetailOut, spawn_id: int, session: AsyncSession
) -> None:
    """Populate equipment on a SpawnOut/SpawnDetailOut DTO.

    One registry_service call per spawn: fine at current scale, noted for
    future batching if the list endpoint becomes a performance concern.
    The session is passed through so the query uses the DI-overridden DB
    in tests rather than bypassing it via AsyncSessionLocal.
    """
    from server.registry import service as registry_service

    eq = await registry_service.equipment_for_spawn(spawn_id, session=session)
    out.equipment = EquipmentOut.from_dict(eq)


@router.get("/spawns", response_model=list[SpawnOut])
async def list_spawns(session: AsyncSession = Depends(get_session)) -> list[SpawnOut]:
    rows = await spawn_service.list_spawns(session)
    for out in rows:
        await _attach_equipment(out, out.id, session)
    return rows


@router.put("/spawns/{spawn_id}/equipment", response_model=SpawnDetailOut)
async def update_equipment(
    spawn_id: int,
    body: EquipmentUpdateIn,
    session: AsyncSession = Depends(get_session),
) -> SpawnDetailOut:
    from server.registry import service as registry_service

    detail = await spawn_service.get_detail(session, spawn_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Spawn not found")
    try:
        await registry_service.replace_user_equipment(
            session, spawn_id, body.toolsets, body.skills
        )
    except registry_service.NotAssignableError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    detail = await spawn_service.get_detail(session, spawn_id)
    assert detail is not None
    await _attach_equipment(detail, spawn_id, session)
    return detail

