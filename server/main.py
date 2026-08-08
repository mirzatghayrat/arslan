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

# Undecryptable-key canary message (module-level so tests can pin the guidance).
# The last sentence points at the most common real-world cause since first-run
# secret auto-generation landed: switching between an explicit ARSLAN_SECRET_KEY
# and the persisted dev file changes the effective secret.
_UNDECRYPTABLE_KEYS_MSG = (
    "%d stored provider API key(s) cannot be decrypted — ARSLAN_SECRET_KEY has "
    "changed since they were saved, so they read as EMPTY (the BYOK adapter has no "
    "credential). Re-enter them in Settings and pin a stable ARSLAN_SECRET_KEY. "
    "If you recently switched between an explicit ARSLAN_SECRET_KEY and the "
    "auto-generated dev secret (~/.arslan/secret_key, or ARSLAN_SECRET_KEY_FILE), "
    "that mismatch is the likely cause."
)


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

    # Stripped on purpose: crypto treats a whitespace-only secret as UNSET
    # (server.crypto._active_secret), so booting prod with one would only defer
    # the failure to the first encrypt(). Fail fast at boot instead.
    if cfg.is_prod and not cfg.secret_key.strip():
        # NOTE: do not interpolate any configured secret (api_token/secret_key/
        # etc.) into this message — only name what is missing.
        raise RuntimeError(
            "ARSLAN_ENV=prod requires ARSLAN_SECRET_KEY (a long random value); "
            "refusing to start. Set it in the environment."
        )

    if not cfg.secret_key.strip():
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


def _log_data_location(cfg, *, log: logging.Logger = logger) -> None:
    """Info-level boot line naming the RESOLVED ABSOLUTE data/db location.

    The default data dir is a stable per-platform app-data path now (not the old
    CWD-relative ``./data``), so logging the absolute location lets a stranger see
    exactly where their brain lives regardless of where uvicorn was launched from.
    """
    from pathlib import Path

    log.info(
        "Arslan data dir: %s  (db: %s)",
        cfg.data_dir,
        Path(cfg.db_path).resolve(),
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

    _log_data_location(settings)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        from server.db.migrations import runner as migration_runner
        await conn.run_sync(migration_runner.apply_pending)
        # Install the PBKDF2 salt BEFORE anything can decrypt. Ordered after the
        # migration chain because 0039 is what adopts a pre-existing on-disk salt
        # into the database, and inside the same transaction so a boot that fails
        # here leaves no half-written salt row behind. crypto refuses to derive
        # without this, so a silent misordering surfaces as a loud error rather
        # than as keys derived from a guessed salt.
        from server.services import crypto_boot
        await conn.run_sync(crypto_boot.resolve_and_adopt_salt)

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

    # E1 reaper: re-enqueue judge scoring for runs stuck in 'recorded'/'score_failed'
    # for >10 minutes (process died around the fire-and-forget scoring task). The judge
    # must see every live run or the evolution corpus silently starves. Best-effort.
    # S3-M1: first sweep orphaned 'recording' rows to 'interrupted' — a run never
    # survives a process restart (the run registry is process-local).
    try:
        from server.services import run_reaper

        await run_reaper.mark_interrupted_runs()
        await run_reaper.reap_stuck_runs()
    except Exception as exc:  # noqa: BLE001 — reaper must never block boot
        logger.warning("run reaper failed (non-fatal): %s", exc)

    # Undecryptable-key canary: if any stored BYOK provider key can't be decrypted, the
    # ARSLAN_SECRET_KEY differs from the one that stored it — EVERY such key silently reads
    # as empty and the LLM adapter has no credential (a dead-adapter root cause; see E9-b).
    # Surface it loudly so the operator re-enters keys and pins a stable secret, instead of
    # chasing a "reachable_no_list"/"requires API key" ghost. Best-effort; never blocks boot.
    try:
        from server.services import provider_config_service

        async with AsyncSessionLocal() as db:
            n_undecryptable = await provider_config_service.count_undecryptable_keys(db)
        if n_undecryptable:
            logger.warning(_UNDECRYPTABLE_KEYS_MSG, n_undecryptable)
    except Exception as exc:  # noqa: BLE001 — key canary must never block boot
        logger.warning("provider-key decryptability canary failed (non-fatal): %s", exc)

    # E9 baseline canary: once the developer has declared a clean-corpus baseline, count LIVE
    # runs created after it that STILL carry epoch=0. A non-zero count means some run-creation
    # path is missing the epoch=1 stamp — those runs will never enter the corpus, silently
    # starving evolution. Log a WARNING so the missed path is visible. Best-effort; never blocks.
    try:
        from server.services import replay_gate

        async with AsyncSessionLocal() as db:
            starved = await replay_gate.count_epoch0_after_baseline(db)
        if starved > 0:
            logger.warning(
                "evolution canary: %d live runs created after baseline carry epoch=0 — a "
                "run-creation path is missing epoch=1; corpus may be starved", starved)
    except Exception as exc:  # noqa: BLE001 — canary must never block boot
        logger.warning("evolution baseline canary failed (non-fatal): %s", exc)

    # E5 evolution watcher: a supervised background loop that, per spawn, checks the
    # trigger (new replayable runs since the last attempt >= the backoff threshold), runs
    # attempts within the token budget, and refreshes living proposals. Best-effort start —
    # never blocks boot; a long interval keeps it idle-cheap.
    try:
        from server.services import evolution_watcher

        evolution_watcher.start()
    except Exception as exc:  # noqa: BLE001 — watcher start must never block boot
        logger.warning("evolution watcher start failed (non-fatal): %s", exc)

    # S3-M4 scheduler: a second supervised loop (60s tick, own task set — independent
    # of the evolution watcher's) that fires due scheduled tasks headless
    # (RunRecorder kind='scheduled' + dispatcher.dispatch). It sweeps orphaned
    # in-flight rows before its first tick. Best-effort start — never blocks boot.
    try:
        from server.services import scheduler

        scheduler.start()
    except Exception as exc:  # noqa: BLE001 — scheduler start must never block boot
        logger.warning("scheduler start failed (non-fatal): %s", exc)

    # 整理层: a third supervised loop (15min tick) that distills conversations whose
    # session_ended never fired. It waits INITIAL_DELAY before its first tick so a boot
    # never immediately spends on LLM calls, and every tick re-reads BOTH kill switches
    # (curation_enabled AND distill_on_session_end). Best-effort start.
    try:
        from server.services import curation_loop

        curation_loop.start()
    except Exception as exc:  # noqa: BLE001 — curation start must never block boot
        logger.warning("curation loop start failed (non-fatal): %s", exc)

    # Drive the inbound MCP server's streamable-http session manager for the app's
    # lifetime (Nail 1: a mounted sub-app's lifespan is NOT auto-run by Starlette).
    mcp_server = getattr(app.state, "mcp_server", None)
    if mcp_server is not None:
        async with mcp_server.session_manager.run():
            yield
    else:  # defensive: app built without the mount
        yield

    try:
        from server.services import evolution_watcher as _evo_watcher

        await _evo_watcher.stop()
    except Exception as exc:  # noqa: BLE001 — watcher stop must never block shutdown
        logger.warning("evolution watcher stop failed (non-fatal): %s", exc)

    try:
        from server.services import scheduler as _scheduler

        await _scheduler.stop()
    except Exception as exc:  # noqa: BLE001 — scheduler stop must never block shutdown
        logger.warning("scheduler stop failed (non-fatal): %s", exc)

    try:
        from server.services import curation_loop as _curation

        await _curation.stop()
    except Exception as exc:  # noqa: BLE001 — curation stop must never block shutdown
        logger.warning("curation loop stop failed (non-fatal): %s", exc)

    from server.mcp.session import manager as _mcp_manager
    await _mcp_manager.aclose_all()


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    app = FastAPI(title="Arslan Server", version="0.1.0", lifespan=lifespan)

    # S1 OSS safety: any secret-write path (provider api_key, settings secrets, MCP
    # env) that would encrypt under the PUBLIC dev fallback key raises
    # InsecureSecretStoreError from crypto.encrypt(). Map it to a clean 400 with the
    # actionable guidance so the client never sees an opaque 500. Covers every write
    # endpoint uniformly (fail-closed at the crypto source, translated here).
    from fastapi.responses import JSONResponse

    from server.crypto import InsecureSecretStoreError

    @app.exception_handler(InsecureSecretStoreError)
    async def _insecure_secret_store_handler(_request, exc: InsecureSecretStoreError):  # noqa: ANN202
        return JSONResponse(status_code=400, content={"detail": str(exc)})

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
    # S4.1-C: MCP-token generate/view/disable — NO require_auth, localhost-gated in handlers.
    app.include_router(settings_api.mcp_token_router, prefix="/api/v1")

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

    from server.api import usage as usage_api

    app.include_router(usage_api.router, prefix="/api/v1")

    from server.api import scheduled_tasks as scheduled_tasks_api

    app.include_router(scheduled_tasks_api.router, prefix="/api/v1")

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

    # --- S4.1-C inbound MCP server: off-by-default, dedicated-token-gated mount ---
    # Mounted BEFORE the SPA catch-all so /mcp-server is not swallowed. The gate is
    # fail-closed & independent of require_auth; session_manager.run() is driven from
    # lifespan() below (Starlette does not auto-run a mounted sub-app's lifespan).
    from server.mcp_server.gate import McpServerGate
    from server.mcp_server.server import build_mcp_server

    mcp_server = build_mcp_server()
    app.state.mcp_server = mcp_server
    _mcp_app = mcp_server.streamable_http_app()  # lazily creates session_manager
    app.mount("/mcp-server", McpServerGate(_mcp_app))

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
