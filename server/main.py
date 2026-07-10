"""FastAPI application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, WebSocket

from server.api import health, settings as settings_api
from server.auth import require_auth
from server.db.models import Base
from server.db.session import engine

logger = logging.getLogger(__name__)


def _validate_settings(cfg, *, active_token: str | None = None, log: logging.Logger = logger) -> None:
    """Boot-fatal + advisory checks on effective settings.

    Called at lifespan startup so it raises BEFORE the server serves any
    request. Guarantees:
      - prod + missing ARSLAN_SECRET_KEY -> refuse to boot (RuntimeError).
        The message names only what is missing; it never echoes any configured
        secret value.
      - dev + missing secret -> keep booting; crypto.py supplies a deterministic
        dev fallback key, so we only warn once.
      - no ACTIVE token -> startup banner (all API/WS unauthenticated). In prod /
        packaged / non-loopback binds ``server.token_bootstrap`` mints one before
        this runs, so the banner only shows for the dev+localhost zero-friction
        flow. (Prod used to refuse boot on an empty token; that hard failure is
        superseded by the S1-3 bootstrap, which auto-generates + enforces one.)
      - 0.0.0.0 bind (best-effort) + no active token -> network-exposure advisory.

    ``active_token`` is the effective token after bootstrap (explicit env token or
    a boot-minted one). It defaults to ``cfg.api_token`` so direct unit callers see
    the raw explicit-token behaviour.
    """
    import os

    if active_token is None:
        active_token = cfg.api_token

    if cfg.is_prod and not cfg.secret_key:
        # NOTE: do not interpolate any configured secret (api_token/secret_key/
        # etc.) into this message — only name what is missing.
        raise RuntimeError(
            "ARSLAN_ENV=prod requires ARSLAN_SECRET_KEY (a long random value); "
            "refusing to start. Set it in the environment."
        )

    if not cfg.secret_key:
        log.warning(
            "ARSLAN_SECRET_KEY not set: using an insecure fixed dev key. Stored "
            "LLM keys are only weakly protected — set ARSLAN_SECRET_KEY (a long "
            "random value) before any non-local deployment."
        )

    if not active_token:
        # Only reachable in dev+localhost now — prod/packaged/non-loopback boots
        # mint a token in token_bootstrap before this runs.
        log.warning(
            "⚠ ARSLAN_API_TOKEN not set: ALL API/WS endpoints are "
            "UNAUTHENTICATED — intended for localhost only."
        )

    # Bind advisory. The real bind host is the launcher's `uvicorn --host`; the
    # app cannot force it, so this is best-effort from ARSLAN_BIND_HOST/HOST.
    effective_host = os.environ.get("HOST") or cfg.bind_host
    if effective_host == "0.0.0.0" and not active_token:  # noqa: S104 — advisory check, not a bind
        log.warning(
            "⚠ Binding 0.0.0.0 with no API token — the API is exposed to the "
            "network with no auth. Set ARSLAN_API_TOKEN or bind 127.0.0.1."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables and run boot migrations/backfills on startup."""
    import os
    from pathlib import Path

    from server import auth, token_bootstrap
    from server.config import settings
    from server.db.session import AsyncSessionLocal

    # S1-3: mint/load an access token when this deployment must be authenticated
    # (prod / packaged / non-loopback bind) and no explicit ARSLAN_API_TOKEN was
    # given. Dev+localhost stays zero-friction (no token, no file). Runs BEFORE
    # validation so the banner/advisory below reflect the effective token.
    token_bootstrap.bootstrap_api_token(settings)

    # Boot-fatal secret/auth validation must run before anything is served.
    _validate_settings(settings, active_token=auth.active_token())

    # Ensure data + spawns dirs exist before the DB file is created on first
    # connect (SQLite will not create missing parent directories).
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    settings.spawns_dir.mkdir(parents=True, exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        from server.db.migrations.versions._0006_provider_configs import (
            upgrade_sync as _backfill_provider_configs,
        )
        await conn.run_sync(_backfill_provider_configs)
        from server.db.migrations.versions._0007_runs import upgrade_sync as _runs_upgrade
        await conn.run_sync(_runs_upgrade)
        from server.db.migrations.versions._0008_evolution_proposals import upgrade_sync as _evo_upgrade
        await conn.run_sync(_evo_upgrade)
        from server.db.migrations.versions._0009_knowledge import upgrade_sync as _kb_upgrade
        await conn.run_sync(_kb_upgrade)
        from server.db.migrations.versions._0010_mcp_servers import upgrade_sync as _mcp_upgrade
        await conn.run_sync(_mcp_upgrade)
        from server.db.migrations.versions._0011_mcp_http_host import upgrade_sync as _mcp2_upgrade
        await conn.run_sync(_mcp2_upgrade)
        from server.db.migrations.versions._0012_discovery_candidates import upgrade_sync as _disc_upgrade
        await conn.run_sync(_disc_upgrade)
        from server.db.migrations.versions._0013_distilled_sessions import upgrade_sync as _distilled_upgrade
        await conn.run_sync(_distilled_upgrade)
        from server.db.migrations.versions._0014_chat_archived import upgrade_sync as _chat_archived_upgrade
        await conn.run_sync(_chat_archived_upgrade)
        from server.db.migrations.versions._0015_persona_seeds import upgrade_sync as _persona_fts_upgrade
        await conn.run_sync(_persona_fts_upgrade)
        from server.db.migrations.versions._0016_spawn_is_default import upgrade_sync as _spawn_default_upgrade
        await conn.run_sync(_spawn_default_upgrade)
        from server.db.migrations.versions._0017_skill_candidates import upgrade_sync as _skill_candidates_upgrade
        await conn.run_sync(_skill_candidates_upgrade)
        from server.db.migrations.versions._0018_second_brain import upgrade_sync as _second_brain_upgrade
        await conn.run_sync(_second_brain_upgrade)
        from server.db.migrations.versions._0019_fact_category import upgrade_sync as _fact_cat_upgrade
        await conn.run_sync(_fact_cat_upgrade)
        from server.db.migrations.versions._0020_fact_label import upgrade_sync as _fact_label_upgrade
        await conn.run_sync(_fact_label_upgrade)
        from server.db.migrations.versions._0021_run_detail import upgrade_sync as _run_detail_upgrade
        await conn.run_sync(_run_detail_upgrade)
        from server.db.migrations.versions._0022_run_created_idx import upgrade_sync as _run_created_idx_upgrade
        await conn.run_sync(_run_created_idx_upgrade)
        from server.db.migrations.versions._0023_run_kb_sources import upgrade_sync as _run_kb_sources_upgrade
        await conn.run_sync(_run_kb_sources_upgrade)
        from server.db.migrations.versions._0024_conversation_events import upgrade_sync as _conversation_events_upgrade
        await conn.run_sync(_conversation_events_upgrade)
        from server.db.migrations.versions._0025_second_brain_rebuild import upgrade_sync as _sb_rebuild_upgrade
        await conn.run_sync(_sb_rebuild_upgrade)
        from server.db.migrations.versions._0026_notes import upgrade_sync as _notes_upgrade
        await conn.run_sync(_notes_upgrade)
        from server.db.migrations.versions._0027_mcp_health import upgrade_sync as _mcp_health_upgrade
        await conn.run_sync(_mcp_health_upgrade)

    from server.registry.seeder import seed_registry

    await seed_registry()

    from server.services.default_spawns import seed_default_spawns

    await seed_default_spawns()

    # PB-4 opt-in boot health sweep: probe every registered MCP server once (sequential,
    # 10s bound each). Default OFF; no background timers. Fail-open — never blocks boot.
    if os.environ.get("ARSLAN_MCP_HEALTH_ON_BOOT") == "1":
        try:
            from server.services import mcp_service

            await mcp_service.check_health_all()
        except Exception as exc:  # noqa: BLE001 — boot sweep must never break startup
            logger.warning("MCP boot health sweep failed (non-fatal): %s", exc)

    # Non-blocking boot backfill for any fact left with category=NULL (write-time
    # classify failed / process died mid-flight / pre-existing rows). Fire-and-forget;
    # wrapped defensively so nothing here can ever abort startup before `yield`.
    try:
        from server.services import fact_classify

        fact_classify.schedule(fact_classify.classify_missing())
    except Exception:  # noqa: BLE001 — boot backfill must never block/break startup
        pass

    # Privacy retention sweep: redact sensitive/bulky run debug detail
    # (system_prompt, injected_kb, per-step args_full/result_raw) for runs older
    # than the configured retention window (default 30 days). Best-effort — a
    # sweep failure must never block boot.
    try:
        from server.services import run_redact, settings_service

        async with AsyncSessionLocal() as db:
            retention_days = await settings_service.run_debug_retention_days(db)
        await run_redact.sweep(retention_days)
    except Exception as exc:  # noqa: BLE001 — retention sweep must never block boot
        logger.warning("run debug retention sweep failed (non-fatal): %s", exc)
    yield

    from server.mcp.session import manager as _mcp_manager
    await _mcp_manager.aclose_all()


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    app = FastAPI(title="Arslan Server", version="0.1.0", lifespan=lifespan)

    # S1 OSS safety: a localhost-bound service with no Host validation is reachable
    # by any web page the user visits (DNS rebinding), and browsers can open
    # cross-site WebSockets. Install the two edge middlewares here; the WS handlers
    # add the per-connection Origin check (CORS does not cover the WS handshake).
    from starlette.middleware.cors import CORSMiddleware
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    from server import security

    # add_middleware wraps in reverse order → TrustedHost (added last) is outermost,
    # so a foreign Host is rejected before CORS/routing runs. CORS uses an explicit
    # allowlist (dev: the vite dev server; prod: ARSLAN_ALLOWED_ORIGINS) — never
    # '*' with credentials.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=security.cors_allow_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=security.trusted_allowed_hosts(),
    )

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(settings_api.router, prefix="/api/v1")
    # S1-3: access-token view/reset — NO require_auth (a packaged user must be able
    # to discover the token), localhost-gated inside the handlers instead.
    app.include_router(settings_api.access_token_router, prefix="/api/v1")

    from server.api import spawns as spawns_api

    app.include_router(spawns_api.router, prefix="/api/v1")

    # Test-only helper to seed a spawn without going through the build socket.
    # It creates a spawn with NO auth, so gate it twice: it must be explicitly
    # opted in via ARSLAN_TEST_ROUTES=1 AND never register in prod — even if the
    # flag leaks into a prod deployment (defense in depth, P0-3).
    import os

    from server.config import settings as _test_route_settings

    if (
        os.environ.get("ARSLAN_TEST_ROUTES") == "1"
        and not _test_route_settings.is_prod
    ):
        _register_test_routes(app)

    from server.api import templates as templates_api

    app.include_router(templates_api.router, prefix="/api/v1")

    from server.api import evolution as evolution_api

    app.include_router(evolution_api.router, prefix="/api/v1")

    from server.api import facts as facts_api

    app.include_router(facts_api.router, prefix="/api/v1")

    from server.api import registry as registry_api

    app.include_router(registry_api.router, prefix="/api/v1")

    from server.api import create as create_api

    app.include_router(create_api.router, prefix="/api/v1")

    from server.api import orchestrator as orchestrator_api

    app.include_router(orchestrator_api.router, prefix="/api/v1")

    from server.api import seeds as seeds_api

    app.include_router(seeds_api.router, prefix="/api/v1")

    from server.api import runs as runs_api

    app.include_router(runs_api.router, prefix="/api/v1")

    from server.api import conversations as conversations_api

    app.include_router(conversations_api.router, prefix="/api/v1")

    from server.api import knowledge as knowledge_api

    app.include_router(knowledge_api.router, prefix="/api/v1")

    from server.api import collections as collections_api

    app.include_router(collections_api.router, prefix="/api/v1")

    from server.api import brain as brain_api

    app.include_router(brain_api.router, prefix="/api/v1")

    from server.api import notes as notes_api

    app.include_router(notes_api.router, prefix="/api/v1")

    from server.api import embedding as embedding_api

    app.include_router(embedding_api.router, prefix="/api/v1")

    from server.api.extract import router as extract_router

    app.include_router(extract_router)

    from server.api.mcp import router as mcp_router

    app.include_router(mcp_router, prefix="/api/v1")

    from server.api import discovery as discovery_api

    app.include_router(discovery_api.router, prefix="/api/v1")

    from server.api import skills as skills_api

    app.include_router(skills_api.router, prefix="/api/v1")

    @app.get("/api/v1/_authcheck", dependencies=[Depends(require_auth)])
    async def _authcheck() -> dict[str, bool]:
        return {"ok": True}

    from server.ws.chat import chat_endpoint

    @app.websocket("/ws/chat/{spawn_id}")
    async def _ws_chat(websocket: WebSocket, spawn_id: int):  # noqa: ANN202
        await chat_endpoint(websocket, spawn_id)

    from server.ws.arslan import arslan_endpoint

    @app.websocket("/ws/arslan/{conversation_id}")
    async def _ws_arslan(websocket: WebSocket, conversation_id: str):  # noqa: ANN202
        await arslan_endpoint(websocket, conversation_id)

    from server.ws.sandbox import sandbox_endpoint

    @app.websocket("/ws/sandbox/{spawn_id}")
    async def _ws_sandbox(websocket: WebSocket, spawn_id: int):  # noqa: ANN202
        await sandbox_endpoint(websocket, spawn_id)

    import os
    from pathlib import Path

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    from server.config import settings as _settings

    static_dir = Path(_settings.static_dir)
    if static_dir.is_dir():
        assets = static_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        index_file = static_dir / "index.html"
        static_root = static_dir.resolve()

        @app.get("/{full_path:path}")
        async def _spa_fallback(full_path: str):  # noqa: ANN202
            # API and WS routes are matched earlier; anything else serves the SPA.
            # Resolve and confirm containment to prevent path traversal
            # (e.g. percent-encoded "../" escaping the static directory).
            if full_path:
                candidate = (static_dir / full_path).resolve()
                if candidate.is_file() and candidate.is_relative_to(static_root):
                    return FileResponse(str(candidate))
            return FileResponse(str(index_file))

    return app


def _register_test_routes(app: FastAPI) -> None:
    from fastapi import Depends as _Depends
    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

    from server.db.session import get_session as _get_session
    from server.services import spawn_service as _spawn_service

    @app.post("/api/v1/_test/seed_spawn")
    async def _seed_spawn(  # noqa: ANN202
        body: dict, session: _AsyncSession = _Depends(_get_session)
    ):
        spawn = await _spawn_service.create_spawn(
            session,
            name=body.get("name", "test-spawn"),
            domain_category="content-creator",
            domain_subcategory="xiaohongshu",
            capabilities=["content-generation"],
            persona_role="beauty blogger",
            persona_tone="friendly",
            system_prompt="You are a beauty expert.",
            generation_level=1,
        )
        return {"id": spawn.id}


app = create_app()
