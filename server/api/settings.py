"""Settings REST endpoints."""
from __future__ import annotations

import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from arslan.llm.catalog import CATALOG
from arslan.llm.presets import expand_preset, provider_options
from server import auth, config, token_bootstrap
from server.auth import require_auth
from server.db.session import get_session
from server.registry.search_providers import list_providers as list_search_providers
from server.schemas import AccessTokenOut, CatalogEntryOut, HealthOut, McpTokenOut, ModelListOut, SearchProbeIn, SearchProbeOut, ProviderConfigIn, ProviderConfigOut, ProviderConfigUpdateIn, ProviderOption, SettingsIn, SettingsOut, SuggestPrimaryOut, TestLLMIn, TestLLMOut
# model_catalog + provider_health are Settings-only: this module is their ONLY
# allowed import site outside their own tests (Provider-round iron rule —
# never from the chat path).
from server.services import model_catalog, provider_config_service, provider_health, searxng_probe, settings_service
from server.services.llm_test import test_connection
from server.services.settings_service import _looks_masked

router = APIRouter(dependencies=[Depends(require_auth)])

# S1-3: the access-token view/reset endpoints must be reachable BEFORE the caller
# knows the token (a packaged user has to discover it), so they live on a router
# with NO require_auth dependency and are gated on the *client host* instead: only
# a DIRECT loopback caller (same machine) may read or rotate the token. A remote caller
# gets `token_required` but never the value, and cannot reset. This closes the
# "packaged user locked out" gap without opening the token to the network.
access_token_router = APIRouter()

# FIX 3: request.client.host reflects X-Forwarded-For when uvicorn runs with
# --proxy-headers, so a remote client behind a trusted proxy could spoof 127.0.0.1 and
# read/rotate the token. A GENUINE direct loopback connection never carries a
# forwarding header, so their presence disqualifies the request regardless of the
# reported client host. (Belt-and-suspenders: reset additionally requires the bearer.)
_FORWARDING_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded")


def _is_direct_localhost(request: Request) -> bool:
    """True only for a genuine DIRECT loopback connection (no proxy in front)."""
    client = request.client
    if not (client and token_bootstrap.is_loopback_host(client.host)):
        return False
    return not any(h in request.headers for h in _FORWARDING_HEADERS)


def _bearer_matches(request: Request, expected: str) -> bool:
    """True when the request's ``Authorization: Bearer <tok>`` matches ``expected``."""
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    token = value.strip()
    return (
        scheme.lower() == "bearer"
        and bool(token)
        and secrets.compare_digest(token, expected)
    )


@access_token_router.get("/settings/access-token", response_model=AccessTokenOut)
async def get_access_token(request: Request) -> AccessTokenOut:
    """Report whether auth is required, and (direct-localhost only) the active token.

    ``active_token()`` returns the authoritative token — the explicit ARSLAN_API_TOKEN
    when env-managed, else the boot-minted one — so a direct-localhost caller sees the
    value that actually gates the API (honest even under an env override). A remote /
    proxy-forwarded caller learns only that auth is required, never the value.
    """
    active = auth.active_token()
    token = active if (active and _is_direct_localhost(request)) else None
    return AccessTokenOut(token_required=bool(active), token=token)


@access_token_router.post("/settings/access-token/reset", response_model=AccessTokenOut)
async def reset_access_token(request: Request) -> AccessTokenOut:
    """Rotate the access token. The old token stops working.

    Rule (FIX 2 + FIX 3): allow only when the request is a DIRECT loopback connection
    (no proxy-forwarding header) AND carries the CURRENT token as a bearer. If the token
    is env-managed (ARSLAN_API_TOKEN set) the rotation cannot take effect — auth always
    prefers the env token — so we refuse with an actionable 409 instead of minting a
    dead token that would lock the user out.
    """
    if not _is_direct_localhost(request):
        raise HTTPException(status_code=403, detail="access-token reset is localhost-only")
    if config.settings.api_token:
        raise HTTPException(
            status_code=409,
            detail="Access token is set via the ARSLAN_API_TOKEN environment variable; "
                   "rotate it there, not here.")
    active = auth.active_token()
    if active and not _bearer_matches(request, active):
        raise HTTPException(
            status_code=401,
            detail="present the current access token to rotate it",
            headers={"WWW-Authenticate": "Bearer"})
    token = token_bootstrap.reset_api_token(config.settings)
    return AccessTokenOut(token_required=True, token=token)


# S4.1-C: dedicated inbound-MCP token (separate from the app api_token, see
# server/mcp_server/token_store.py). Generation is localhost-gated only — no old-token
# challenge — because this feature is optional (no lockout risk the way the app's own
# access token has): a fresh generate simply rotates. Show-once (spec Q3 detail 2): the
# full plaintext is returned ONLY by generate, exactly once; GET never re-shows it.
mcp_token_router = APIRouter()


@mcp_token_router.get("/settings/mcp-token", response_model=McpTokenOut)
async def get_mcp_token(db: AsyncSession = Depends(get_session)) -> McpTokenOut:
    # Show-once: GET reports only whether a token exists + the enabled flag; the full
    # token value is returned ONLY by the generate endpoint, once.
    from server.mcp_server import token_store
    enabled = await settings_service.mcp_server_enabled(db)
    return McpTokenOut(enabled=enabled, token_set=bool(token_store.read_mcp_token()), token=None)


@mcp_token_router.post("/settings/mcp-token/generate", response_model=McpTokenOut)
async def generate_mcp_token(request: Request, db: AsyncSession = Depends(get_session)) -> McpTokenOut:
    if not _is_direct_localhost(request):
        raise HTTPException(status_code=403, detail="MCP token generation is localhost-only")
    from server.mcp_server import token_store
    token = token_store.generate_mcp_token()
    enabled = await settings_service.mcp_server_enabled(db)
    return McpTokenOut(enabled=enabled, token_set=True, token=token)


@mcp_token_router.post("/settings/mcp-token/disable", response_model=McpTokenOut)
async def disable_mcp_token(request: Request, db: AsyncSession = Depends(get_session)) -> McpTokenOut:
    if not _is_direct_localhost(request):
        raise HTTPException(status_code=403, detail="MCP token control is localhost-only")
    from server.mcp_server import token_store
    token_store.clear_mcp_token()
    enabled = await settings_service.mcp_server_enabled(db)
    return McpTokenOut(enabled=enabled, token_set=False, token=None)


@router.get("/settings/providers", response_model=list[ProviderOption])
async def list_providers() -> list[ProviderOption]:
    """Available LLM providers for the Settings dropdown (Tier-0 presets + native)."""
    return [ProviderOption(**o) for o in provider_options()]


@router.get("/settings/search-providers", response_model=list[str])
async def search_providers() -> list[str]:
    """Registered web-search providers for the Settings dropdown (Tavily default)."""
    return list_search_providers()


@router.get("/settings/crypto-health", response_model=dict)
async def crypto_health(session: AsyncSession = Depends(get_session)) -> dict:
    """Why stored secrets cannot be read, as a machine verdict the UI localizes.

    Read-only, and it carries no plaintext and no salt bytes — see
    ``crypto_boot.diagnose``. Deliberately a verdict KEY rather than a sentence: the
    one hard-coded sentence this replaces (``settings.keyUndecryptableReason``) named
    ARSLAN_SECRET_KEY as the cause of what was actually a salt change, and a specific
    wrong cause costs more than no cause at all.
    """
    from server.services import crypto_boot

    # session.connection(), not session.run_sync(): the latter hands the callable a
    # sync *Session*, and diagnose() speaks to a *Connection* (exec_driver_sql). Every
    # unit test drives it with a connection already, so only an over-the-wire test
    # could surface this — which is what caught it.
    conn = await session.connection()
    return await conn.run_sync(crypto_boot.diagnose)


@router.get("/settings/ocr-languages", response_model=dict)
async def ocr_languages() -> dict:
    """What THIS machine's text recognition can read, asked at request time.

    Not a constant, and not a list we maintain: the set grows with the macOS
    version, so a hardcoded one would describe the developer's machine and
    promise the user something their system may not do. On a host without the
    framework the list is empty and the UI says so rather than offering
    choices that would do nothing.

    `max_selectable` is a MEASURED limit, not tidiness. Recognition degrades as
    the requested list grows and CJK is the first casualty: asking for all
    thirty supported languages returns only the English line from a mixed
    Chinese/English image, and nothing at all from a Japanese one, while
    ("zh-Hans", "en-US") reads both. A picker with no ceiling would let someone
    destroy the capability they were trying to widen.
    """
    from server.services import ocr_vision

    return {
        "available": list(ocr_vision.supported_languages()),
        "max_selectable": ocr_vision.MAX_REQUESTED_LANGUAGES,
        "platform_supported": ocr_vision.is_available(),
    }


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
    try:
        return await provider_config_service.add_config(
            session, label=body.label, provider=body.provider, model=body.model,
            base_url=body.base_url, api_key=body.api_key)
    except ValueError as exc:  # P3: custom without base_url
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.put("/settings/provider-configs/{config_id}", response_model=ProviderConfigOut)
async def update_provider_config(config_id: int, body: ProviderConfigUpdateIn,
                                 session: AsyncSession = Depends(get_session)):
    try:
        updated = await provider_config_service.update_config(
            session, config_id, label=body.label, provider=body.provider, model=body.model,
            base_url=body.base_url, api_key=body.api_key)
    except ValueError as exc:  # P3: patch would leave a custom config without base_url
        raise HTTPException(status_code=422, detail=str(exc)) from None
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


@router.get("/settings/provider-configs/{config_id}/models", response_model=ModelListOut)
async def list_provider_config_models(
    config_id: int, refresh: bool = False,
    session: AsyncSession = Depends(get_session),
) -> ModelListOut:
    """Dynamic model list for one saved provider config (Provider-P2).

    Cache-first (5min fresh / 24h stale-ok, local hosts refetch eagerly);
    ``?refresh=true`` forces a live fetch. Never 5xx on network failure —
    degrades to the stale cache, then the static seed (source="static").
    """
    try:
        result = await model_catalog.get_models(session, config_id, refresh=refresh)
    except LookupError:
        raise HTTPException(status_code=404, detail="provider config not found") from None
    return ModelListOut(**result)


@router.post("/settings/test-llm", response_model=TestLLMOut)
async def test_llm_raw(body: TestLLMIn) -> TestLLMOut:
    """Test a raw LLM config (provider, model, base_url, api_key) without saving it.

    Returns {ok, error, latency_ms}.  Never raises a 5xx — errors come back as
    {ok: false, error: "…"}.
    """
    # D3 empty-key unification: an empty key is a legitimate config (keyless
    # local servers) and proceeds to the real connection test — consistent
    # with the saved-config path below. Only a masked echo is rejected.
    if body.api_key and _looks_masked(body.api_key):
        return TestLLMOut(ok=False, error="enter a real API key to test")
    result = await test_connection(
        provider=body.provider,
        model=body.model,
        base_url=body.base_url,
        api_key=body.api_key,
    )
    return TestLLMOut(**result)


@router.post("/settings/test-search-instance", response_model=SearchProbeOut)
async def test_search_instance(body: SearchProbeIn) -> SearchProbeOut:
    """Test a self-hosted SearXNG address without saving it.

    Never raises: every failure is one of the four verdicts, because a 500 here would
    tell the user "something went wrong" — which is the sentence this endpoint exists
    to replace.
    """
    if not body.base_url.strip():
        return SearchProbeOut(verdict="unreachable",
                              detail="enter the instance address first")
    return SearchProbeOut(**await searxng_probe.probe(body.base_url.strip()))


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


@router.post("/settings/provider-configs/{config_id}/health", response_model=HealthOut)
async def probe_provider_config_health(
    config_id: int, session: AsyncSession = Depends(get_session)
) -> HealthOut:
    """Tri-state connectivity probe for one saved provider config (Provider-P4).

    Fires ONLY on explicit Settings interactions (spec decision D4 — no
    background polling). Persists the verdict on the row (last_health /
    last_health_at) so Settings-open can render the last-known state.
    Never 5xx on network failure — that is the "unreachable" state.
    """
    from server.db.models import ProviderConfig
    row = await session.get(ProviderConfig, config_id)
    if row is None:
        raise HTTPException(status_code=404, detail="provider config not found")
    api_key = provider_config_service._safe(row.api_key)
    # Mirror the /models endpoint: probe the expand_preset-resolved base_url
    # with the config-level provider key.
    _, _, base_url = expand_preset(row.provider, row.model, row.base_url or "")
    result = await provider_health.probe(row.provider, base_url, api_key)
    row.last_health = result["state"]
    row.last_health_at = datetime.utcnow()
    await session.commit()
    return HealthOut(state=result["state"], latency_ms=result["latency_ms"],
                     detail=result["detail"],
                     last_health_at=row.last_health_at.isoformat())


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
