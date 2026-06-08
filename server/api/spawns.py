"""Spawn CRUD REST endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.session import get_session
from server.schemas import ConfigUpdateIn, SpawnDetailOut, SpawnOut
from server.services import spawn_service

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/spawns", response_model=list[SpawnOut])
async def list_spawns(session: AsyncSession = Depends(get_session)) -> list[SpawnOut]:
    return await spawn_service.list_spawns(session)


@router.get("/spawns/{spawn_id}", response_model=SpawnDetailOut)
async def get_spawn(
    spawn_id: int, session: AsyncSession = Depends(get_session)
) -> SpawnDetailOut:
    detail = await spawn_service.get_detail(session, spawn_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Spawn not found")
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
    return detail


@router.delete("/spawns/{spawn_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_spawn(
    spawn_id: int, session: AsyncSession = Depends(get_session)
) -> Response:
    ok = await spawn_service.delete_spawn(session, spawn_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Spawn not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
