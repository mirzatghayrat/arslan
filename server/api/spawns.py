"""Spawn CRUD REST endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.models import Spawn
from server.db.session import get_session
from server.schemas import (
    ConfigUpdateIn,
    EquipmentOut,
    EquipmentUpdateIn,
    PreferenceDeleteIn,
    PreferencesOut,
    SpawnDetailOut,
    SpawnOut,
)
from server.services import chat_lifecycle, spawn_service

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


@router.get("/spawns/{spawn_id}", response_model=SpawnDetailOut)
async def get_spawn(
    spawn_id: int, session: AsyncSession = Depends(get_session)
) -> SpawnDetailOut:
    detail = await spawn_service.get_detail(session, spawn_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Spawn not found")
    await _attach_equipment(detail, spawn_id, session)
    return detail


@router.put("/spawns/{spawn_id}/config", response_model=SpawnDetailOut)
async def update_config(
    spawn_id: int,
    body: ConfigUpdateIn,
    session: AsyncSession = Depends(get_session),
) -> SpawnDetailOut:
    spawn = await spawn_service.update_config(
        session, spawn_id, **body.model_dump(exclude_none=True)
    )
    if spawn is None:
        raise HTTPException(status_code=404, detail="Spawn not found")
    detail = await spawn_service.get_detail(session, spawn_id)
    assert detail is not None
    await _attach_equipment(detail, spawn_id, session)
    return detail


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


@router.get("/spawns/{spawn_id}/preferences", response_model=PreferencesOut)
async def get_preferences(spawn_id: int, session: AsyncSession = Depends(get_session)) -> PreferencesOut:
    spawn = await session.get(Spawn, spawn_id)
    if spawn is None:
        raise HTTPException(status_code=404, detail="spawn not found")
    return PreferencesOut(preferences=list(spawn.memory_facts or []))


@router.delete("/spawns/{spawn_id}/preferences", response_model=PreferencesOut)
async def delete_preference(spawn_id: int, body: PreferenceDeleteIn,
                            session: AsyncSession = Depends(get_session)) -> PreferencesOut:
    spawn = await session.get(Spawn, spawn_id)
    if spawn is None:
        raise HTTPException(status_code=404, detail="spawn not found")
    spawn.memory_facts = [f for f in (spawn.memory_facts or []) if f != body.fact]
    await session.commit()
    return PreferencesOut(preferences=list(spawn.memory_facts))


@router.post("/spawns/{spawn_id}/complete-chat")
async def complete_chat(spawn_id: int) -> dict:
    n = await chat_lifecycle.complete_chat(spawn_id)
    return {"ok": True, "archived": n}


@router.delete("/spawns/{spawn_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_spawn(
    spawn_id: int, session: AsyncSession = Depends(get_session)
) -> Response:
    ok = await spawn_service.delete_spawn(session, spawn_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Spawn not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
