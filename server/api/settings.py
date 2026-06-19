"""Settings REST endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from arslan.llm.presets import provider_options
from server.auth import require_auth
from server.db.session import get_session
from server.registry.search_providers import list_providers as list_search_providers
from server.schemas import ProviderOption, SettingsIn, SettingsOut
from server.services import settings_service

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/settings/providers", response_model=list[ProviderOption])
async def list_providers() -> list[ProviderOption]:
    """Available LLM providers for the Settings dropdown (Tier-0 presets + native)."""
    return [ProviderOption(**o) for o in provider_options()]


@router.get("/settings/search-providers", response_model=list[str])
async def search_providers() -> list[str]:
    """Registered web-search providers for the Settings dropdown (Tavily default)."""
    return list_search_providers()


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
