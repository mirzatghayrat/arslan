"""Settings REST endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from arslan.llm.catalog import CATALOG
from arslan.llm.presets import provider_options
from server.auth import require_auth
from server.db.session import get_session
from server.registry.search_providers import list_providers as list_search_providers
from server.schemas import CatalogEntryOut, ProviderConfigIn, ProviderConfigOut, ProviderConfigUpdateIn, ProviderOption, SettingsIn, SettingsOut, SuggestPrimaryOut, TestLLMIn, TestLLMOut
from server.services import provider_config_service, settings_service
from server.services.llm_test import test_connection
from server.services.settings_service import _looks_masked

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


@router.get("/settings/provider-configs", response_model=list[ProviderConfigOut])
async def list_provider_configs(session: AsyncSession = Depends(get_session)):
    return await provider_config_service.list_configs(session)


@router.post("/settings/provider-configs", response_model=ProviderConfigOut)
async def add_provider_config(body: ProviderConfigIn, session: AsyncSession = Depends(get_session)):
    return await provider_config_service.add_config(
        session, label=body.label, provider=body.provider, model=body.model,
        base_url=body.base_url, api_key=body.api_key)


@router.put("/settings/provider-configs/{config_id}", response_model=ProviderConfigOut)
async def update_provider_config(config_id: int, body: ProviderConfigUpdateIn,
                                 session: AsyncSession = Depends(get_session)):
    updated = await provider_config_service.update_config(
        session, config_id, label=body.label, provider=body.provider, model=body.model,
        base_url=body.base_url, api_key=body.api_key)
    if updated is None:
        raise HTTPException(status_code=404, detail="config not found")
    return updated


@router.patch("/settings/provider-configs/{config_id}/primary")
async def set_primary_provider_config(config_id: int, session: AsyncSession = Depends(get_session)):
    await provider_config_service.set_primary(session, config_id)
    return {"ok": True}


@router.delete("/settings/provider-configs/{config_id}")
async def delete_provider_config(config_id: int, session: AsyncSession = Depends(get_session)):
    deleted = await provider_config_service.delete_config(session, config_id)
    if not deleted:
        raise HTTPException(status_code=400, detail="cannot delete the only provider config")
    return {"ok": True}


@router.post("/settings/test-llm", response_model=TestLLMOut)
async def test_llm_raw(body: TestLLMIn) -> TestLLMOut:
    """Test a raw LLM config (provider, model, base_url, api_key) without saving it.

    Returns {ok, error, latency_ms}.  Never raises a 5xx — errors come back as
    {ok: false, error: "…"}.
    """
    if not body.api_key or _looks_masked(body.api_key):
        return TestLLMOut(ok=False, error="enter a real API key to test")
    result = await test_connection(
        provider=body.provider,
        model=body.model,
        base_url=body.base_url,
        api_key=body.api_key,
    )
    return TestLLMOut(**result)


@router.post("/settings/provider-configs/{config_id}/test", response_model=TestLLMOut)
async def test_saved_provider_config(
    config_id: int, session: AsyncSession = Depends(get_session)
) -> TestLLMOut:
    """Test a previously-saved provider config by id using its stored decrypted key.

    Returns {ok, error, latency_ms}.  Returns 404 if the id doesn't exist.
    """
    from server.db.models import ProviderConfig
    row = await session.get(ProviderConfig, config_id)
    if row is None:
        raise HTTPException(status_code=404, detail="provider config not found")
    api_key = provider_config_service._safe(row.api_key)
    result = await test_connection(
        provider=row.provider,
        model=row.model or "",
        base_url=row.base_url or "",
        api_key=api_key,
    )
    return TestLLMOut(**result)


@router.get("/settings/suggest-primary", response_model=SuggestPrimaryOut | None)
async def suggest_primary(session: AsyncSession = Depends(get_session)):
    cfg = await settings_service.get_settings(session)
    return await provider_config_service.suggest_primary(session, cfg.get("language"))


@router.get("/settings/catalog", response_model=list[CatalogEntryOut])
async def get_catalog() -> list[CatalogEntryOut]:
    """Read-only provider capability catalog for the transparency table."""
    return [
        CatalogEntryOut(
            provider=provider,
            capabilities=entry["capabilities"],
            languages=entry["languages"],
        )
        for provider, entry in CATALOG.items()
    ]
