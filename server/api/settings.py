"""Settings REST endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.session import get_session
from server.schemas import SettingsIn, SettingsOut
from server.services import settings_service

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/settings", response_model=SettingsOut)
async def read_settings(session: AsyncSession = Depends(get_session)) -> SettingsOut:
    data = await settings_service.get_settings(session)
    return SettingsOut(**data)


@router.put("/settings", response_model=SettingsOut)
async def write_settings(
    body: SettingsIn, session: AsyncSession = Depends(get_session)
) -> SettingsOut:
    await settings_service.update_settings(session, body.model_dump(exclude_none=True))
    data = await settings_service.get_settings(session)
    return SettingsOut(**data)
