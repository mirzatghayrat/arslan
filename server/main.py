"""FastAPI application factory."""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, WebSocket

from server.api import health, settings as settings_api
from server.auth import require_auth
from server.db.session import engine

logger = logging.getLogger(__name__)


class _QuietDesktopStatusPolls(logging.Filter):
    """The resident desktop shell polls /api/v1/desktop/status every 2 s (0.1.41).
    Logging each poll would bury every other request line; nothing else is muted."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/v1/desktop/status" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_QuietDesktopStatusPolls())


# The value after `token=` (any case): a quoted value whole, closing quote or not (`%r`, bytes, an f-string's
# `!r`, #402 review 1), else up to the next query separator, whitespace or quote. Never a value already
# `[redacted]`: a record on a uvicorn logger gets two passes, and the second must change nothing (re-check).
_TOKEN_IN_LOG_LINE = re.compile(r"(token=)(?!\[redacted\])(?:b?'[^']*'?|b?\"[^\"]*\"?|[^&\s\"']*)",
                                re.IGNORECASE)
# An `Authorization: Bearer` header's value, as the websockets library dumps headers at DEBUG.
_BEARER_IN_LOG_LINE = re.compile(r"(authorization:\s*bearer\s+)(?!\[redacted\])\S+", re.IGNORECASE)
# A value still there after redaction (not the `[redacted]` this file writes).
_SECRET_LEFT = re.compile(r"token=(?!\[redacted\])[^&\s]|authorization:\s*bearer\s+(?!\[redacted\])\S",
                          re.IGNORECASE)


def _secret_left(text: str) -> bool:
    lowered = text.lower()      # most lines carry neither word: a substring test first (#402 re-check)
    return ("token=" in lowered or "bearer" in lowered) and _SECRET_LEFT.search(text) is not None


def _redact(text: str) -> str:
    return _BEARER_IN_LOG_LINE.sub(r"\1[redacted]", _TOKEN_IN_LOG_LINE.sub(r"\1[redacted]", text))


def _without_token(value: object) -> object:
    """A string with every token value replaced, or `value` itself. Only strings are looked into here: anything
    else (the ASGI scope `uvicorn.asgi` logs, an object whose str() raises or reaches a database) is left to the
    finished-line check below, which renders it once, as the handler would."""
    if not isinstance(value, str):
        return value
    lowered = value.lower()
    return _redact(value) if "token=" in lowered or "bearer" in lowered else value


class _RedactAccessTokens(logging.Filter):
    """The access token travels as a `?token=` query parameter on the WebSocket handshake, and
    uvicorn logs the request path with its query string at INFO (`uvicorn.error` for the WebSocket
    lines, `uvicorn.access` for HTTP; `uvicorn.asgi` logs the whole scope at trace level). The
    desktop app runs at INFO with stderr passed through, so without this every handshake wrote the
    token to the log (C11b, #338 review F3). The path and the rest of the query stay readable;
    only the value is replaced. The format string and each string argument are redacted in place,
    and the arguments keep their count and order: uvicorn's AccessFormatter unpacks the five
    access-line arguments itself, so a flattened record would be dropped with a logging error (C11b
    review 1).

    Then the finished line is checked (follow-up to the C11b re-check): a name and value passed in
    separate arguments are only seen together there, a `token=%s` format string loses its
    placeholder to the redaction, and a non-string argument is only rendered there. If the line
    fails to format or a value is left, the record is flattened to its whole line, redacted; one
    that never formats keeps its words and withholds its arguments, and so does a record this
    filter cannot handle at all (#402 review 2)."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg, args = record.msg, record.args
        try:
            record.msg = _without_token(msg)
            if isinstance(args, tuple):
                record.args = tuple(_without_token(a) for a in args)
            elif isinstance(args, dict):
                record.args = {key: _without_token(v) for key, v in args.items()}
            if record.name == "uvicorn.access":
                # Never flattened: AccessFormatter unpacks the five arguments, already redacted one by one, and a
                # request could otherwise turn its own line into a logging error (`/?authorization:bearer` read,
                # across the pieces, as a Bearer value left; #402 re-check).
                return True
            try:
                finished = record.getMessage()
            except Exception:
                finished = None
            if finished is None or _secret_left(finished):
                try:
                    whole = str(msg % args) if args else str(msg)
                except Exception:         # it never formatted: keep the words, never the arguments' values
                    whole = f"{msg} (unformattable arguments withheld)"
                record.msg, record.args = _redact(whole), ()
        except Exception:    # never drop the line, and never let its arguments out unredacted
            record.args = ()
            try:
                record.msg = _redact(f"{msg} (unformattable arguments withheld)")
            except Exception:
                record.msg = "(a log line that could not be rendered was withheld)"
        return True


for _name in ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"):
    logging.getLogger(_name).addFilter(_RedactAccessTokens())


def _install_redacting_record_factory() -> None:
    """Every record, from any logger, is redacted where it is made (#402 review): a logger's filters see only the
    records that start on it, so a child logger (`uvicorn.error.child`) passed `uvicorn.error`'s untouched, and
    FastMCP's root handler shows every other logger's records. Installed once, over whatever factory was set."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "arslan_redacts", False):
        return
    redactor = _RedactAccessTokens()

    def make(*args, **kwargs):
        record = previous(*args, **kwargs)
        redactor.filter(record)
        return record
    make.arslan_redacts = True
    logging.setLogRecordFactory(make)


_install_redacting_record_factory()



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
      - ARSLAN_ENV set to anything but dev -> refuse to boot (prod mode is gone, C11).
      - packaged + no secret (first-boot generation failed) -> refuse to boot
        (RuntimeError). The message names only what is missing; it never echoes
        any configured secret value.
      - dev + missing secret -> keep booting; crypto.py supplies a deterministic
        dev fallback key, so we only warn once.
      - no ACTIVE token -> startup banner (all API/WS unauthenticated). In packaged /
        non-loopback binds ``server.token_bootstrap`` mints one before this runs, so
        the banner only shows for the dev+localhost zero-friction flow.
      - 0.0.0.0 bind (best-effort) + no active token -> network-exposure advisory.

    ``active_token`` is the effective token after bootstrap (explicit env token or
    a boot-minted one). It defaults to ``cfg.api_token`` so direct unit callers see
    the raw explicit-token behaviour.
    """
    import os

    if active_token is None:
        active_token = cfg.api_token

    # 0.1.63 C11: there is no prod mode any more. Refuse rather than quietly run with the dev
    # defaults it used to harden: the desktop app is the supported way to run Arslan.
    if os.environ.get("ARSLAN_ENV", "dev").strip().lower() not in ("", "dev"):
        raise RuntimeError(
            "ARSLAN_ENV is no longer supported (prod mode was removed in v0.1.63); "
            "run the desktop app, or unset ARSLAN_ENV for a local dev server."
        )

    # Stripped on purpose: crypto treats a whitespace-only secret as UNSET
    # (server.crypto._active_secret), so booting with one would only defer the
    # failure to the first encrypt(). The desktop app's server creates and saves
    # its secret on first boot (server.secret_bootstrap); if that failed, it
    # refuses to start rather than store API keys under the public dev key —
    # whatever ARSLAN_ALLOW_INSECURE_SECRETS says (C11).
    if cfg.packaged and not cfg.secret_key.strip():
        # NOTE: do not interpolate any configured secret (api_token/secret_key/
        # etc.) into this message — only name what is missing.
        raise RuntimeError(
            "No secret key: the desktop app could not create or read ~/.arslan/secret_key; "
            "refusing to start. Check that the file is readable, or set ARSLAN_SECRET_KEY."
        )

    if not cfg.secret_key.strip():
        log.warning(
            "ARSLAN_SECRET_KEY not set: using an insecure fixed dev key. Stored "
            "LLM keys are only weakly protected — set ARSLAN_SECRET_KEY (a long "
            "random value) before any non-local deployment."
        )

    if not active_token:
        # Only reachable in dev+localhost now — packaged/non-loopback boots
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


#: Boot work that must never hold up boot (kept referenced until it ends).
_background: set = set()


async def _prune_forgotten() -> None:
    """A deleted server's folder kept under `<data>/mcp/.forgotten/` goes to the user's Trash after
    30 days — off the event loop, behind boot (a move across volumes copies); a failure is logged,
    never raised, and the folders wait for the next boot."""
    import asyncio

    from server.mcp import session as mcp_session

    try:
        moved = await asyncio.to_thread(mcp_session.prune_forgotten)
    except Exception:  # noqa: BLE001 — a folder left for the next boot never matters to this one
        logger.warning("MCP: moving old forgotten folders to the Trash failed (non-fatal)",
                       exc_info=True)
        return
    if moved:
        logger.info("MCP: moved %d forgotten server folder(s) to the Trash", len(moved))


async def _start_mcp_supervisor() -> bool:
    """0.1.61 §B1: every enabled MCP server starts in the background; a chat turn never waits.
    ARSLAN_MCP_SUPERVISOR=0 (the test suite) leaves it off.

    A `ready` left from the last run is never trusted (migration 0068 maps connected → ready):
    `reset_for_boot` makes every switched-on server `starting`. If that write fails, the supervisor
    starts anyway — each plan writes its server's state as it starts — and the reset is retried in
    the background for the rows nothing in this process has written yet. The `.forgotten` prune
    runs in the background too: boot never waits for it (Task 6 fix round 1, F5)."""
    import asyncio

    from server.mcp import supervisor as mcp_supervisor

    if not mcp_supervisor.switched_on():
        return False
    supervisor = mcp_supervisor.supervisor
    try:
        await supervisor.reset_for_boot()
    except Exception:  # noqa: BLE001 — retried in the background; never a reason to keep MCP off
        logger.warning("MCP boot reset failed; the supervisor starts anyway and retries it",
                       exc_info=True)
        supervisor.retry_boot_reset()
    supervisor.start()
    task = asyncio.create_task(_prune_forgotten(), name="mcp-forgotten-prune")
    _background.add(task)
    task.add_done_callback(_background.discard)
    return True


async def _boot_mcp() -> None:
    """MCP at boot (0.1.61 §B1): the supervisor. It never breaks boot."""
    try:
        await _start_mcp_supervisor()
    except Exception as exc:  # noqa: BLE001 — MCP must never break boot
        logger.warning("MCP supervisor start failed (non-fatal): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables and run boot migrations/backfills on startup."""
    app.state.shutdown_complete = False
    from pathlib import Path

    from server import auth, token_bootstrap
    from server.config import settings
    from server.db.session import AsyncSessionLocal

    # S1-3: mint/load an access token when this deployment must be authenticated
    # (packaged / non-loopback bind) and no explicit ARSLAN_API_TOKEN was
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

    from server.services.storage_boot import initialize
    await initialize(engine)

    from server.services import native_locale

    async with AsyncSessionLocal() as native_locale_session:
        await native_locale.sync(native_locale_session)

    # Repair a crash between a committed deletion and its independent file
    # mirror, before requests/background work. Never overwrite a newer ledger.
    from server.services import memory_deletion_ledger
    async with AsyncSessionLocal() as ledger_session:
        await memory_deletion_ledger.sync(ledger_session)

    # 0.1.61 §A5: a "for this task" grant ends with its task, and no turn or job survives a
    # restart: drop every one the last run left, before any request or background work. The
    # conversation grants stay. Best-effort — a failure is logged and never blocks boot.
    try:
        from server.services import permissions

        await permissions.forget_every_task_grant()
    except Exception as exc:  # noqa: BLE001 — must never block boot
        logger.warning("task grants of the last run were not dropped at boot (non-fatal): %s", exc)

    # SBX-3 §1a: a run's own temp folder goes when the run ends, unless a process it started is left; those
    # the last start left go now, once their processes are gone. Best-effort — never blocks boot.
    try:
        from server.services import run_temp

        run_temp.sweep()
    except Exception as exc:  # noqa: BLE001 — must never block boot
        logger.warning("run temp folders of the last start were not swept at boot (non-fatal): %s", exc)

    from server.registry.seeder import seed_registry

    await seed_registry()

    # 0.1.61 §B1: the MCP supervisor starts every enabled server in the background; the PB-4
    # opt-in health sweep runs only when the supervisor is off. Never blocks boot.
    await _boot_mcp()

    # 0.1.48: the built-in example experts are no longer seeded — one Arslan does the work.

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

    # 0.1.52 S2: keep the judgment ledger bounded (90 days, 20k rows). Best-effort.
    try:
        from server.services import judgment
        await judgment.prune()
    except Exception as exc:  # noqa: BLE001
        logger.warning("judgment ledger prune failed (non-fatal): %s", exc)
    # JUDGE1 (the user, 2026-10-31): drop ledger rows holding memory text from before digests. After the prune, in
    # its own try, so a failure here neither skips the prune nor reads as a prune failure (#582 review, L3).
    try:
        from server.services import judgment
        await judgment.drop_unredacted()
    except Exception as exc:  # noqa: BLE001
        logger.warning("judgment ledger clean failed (non-fatal): %s", exc)

    # E1 reaper: re-enqueue judge scoring for runs stuck in 'recorded'/'score_failed'
    # for >10 minutes (process died around the fire-and-forget scoring task). The judge
    # must see every live run or the evolution corpus silently starves. Best-effort.
    # S3-M1: first sweep orphaned 'recording' rows to 'interrupted' — a run never
    # survives a process restart (the run registry is process-local).
    try:
        from server.services import run_reaper

        await run_reaper.mark_interrupted_runs()
        from server.services import task_service
        await task_service.recover_interrupted()
        from server.services import background_jobs
        await background_jobs.report_interrupted()
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

    # S3-M4 scheduler: a second supervised loop (60s tick, own task set — independent
    # of the evolution watcher's) that fires due scheduled tasks headless
    # K4a (v0.1.63): a run that starts at an entry point (a chat turn, a scheduled turn) takes the work
    # budget tier the user picked, as a background job does.
    from arslan import execution_budget
    from server.services import settings_service as _settings_for_budget

    execution_budget.use_budget_factory(_settings_for_budget.run_budget_from_settings)

    # (one Arslan turn per fire, scheduler.run_arslan_turn). It sweeps orphaned
    # in-flight rows before its first tick. Best-effort start — never blocks boot.
    try:
        from server.services import scheduler

        scheduler.start()
        # Reconcile the heartbeat's task with its settings at boot: a build that
        # shipped while it was enabled, or a hand-edited settings row, would
        # otherwise leave the task and the switch disagreeing.
        from server.services import heartbeat

        await heartbeat.sync_task()
    except Exception as exc:  # noqa: BLE001 — scheduler start must never block boot
        logger.warning("scheduler start failed (non-fatal): %s", exc)

    # D5 retention for brain_usage_events (first pass after 5 min, then every 15 min).
    # Not opt-in: brain_usage.record appends on every retrieval, so the log needs its
    # bound on a default install. It rode on the curation loop (整理层) until C8-3
    # (v0.1.63) deleted that loop.
    try:
        from server.services import usage_retention

        usage_retention.start()
    except Exception as exc:  # noqa: BLE001 — retention start must never block boot
        logger.warning("usage retention start failed (non-fatal): %s", exc)

    # 0.1.47 proactivity: a fourth supervised loop (10 min pass, first pass after 60 s).
    # Detectors are deterministic and free; it only stores inbox items, and never
    # acts. Best-effort start.
    try:
        from server.services import proactive_service

        proactive_service.start()
    except Exception as exc:  # noqa: BLE001 — proactivity start must never block boot
        logger.warning("proactive loop start failed (non-fatal): %s", exc)

    # Drive the inbound MCP server's streamable-http session manager for the app's
    # lifetime (Nail 1: a mounted sub-app's lifespan is NOT auto-run by Starlette).
    mcp_server = getattr(app.state, "mcp_server", None)
    if mcp_server is not None:
        async with mcp_server.session_manager.run():
            yield
    else:  # defensive: app built without the mount
        yield

    await _shutdown_services(app)


async def _shutdown_services(app: FastAPI) -> None:
    """A recovery stop is confirmed only after every tracked cleanup succeeds."""
    app.state.shutdown_complete = False
    cleanup_complete = True
    try:
        from server.services import scheduler as _scheduler

        await _scheduler.stop()
    except Exception as exc:  # noqa: BLE001 — scheduler stop must never block shutdown
        cleanup_complete = False
        logger.warning("scheduler stop failed (non-fatal): %s", exc)

    try:
        from server.services import usage_retention as _retention

        await _retention.stop()
    except Exception as exc:  # noqa: BLE001 — retention stop must never block shutdown
        cleanup_complete = False
        logger.warning("usage retention stop failed (non-fatal): %s", exc)

    try:
        from server.services import proactive_service as _proactive

        await _proactive.stop()
    except Exception as exc:  # noqa: BLE001 — proactive stop must never block shutdown
        cleanup_complete = False
        logger.warning("proactive loop stop failed (non-fatal): %s", exc)

    try:
        from server.mcp.supervisor import supervisor as _mcp_supervisor

        await _mcp_supervisor.stop()          # before aclose_all: no retry may reopen a session
    except Exception as exc:  # noqa: BLE001 — supervisor stop must never block shutdown
        cleanup_complete = False
        logger.warning("MCP supervisor stop failed (non-fatal): %s", exc)

    from server.api import browser as _browser_api
    await _browser_api.shutdown()
    from server.mcp.session import manager as _mcp_manager
    await _mcp_manager.aclose_all()
    await engine.dispose()
    app.state.shutdown_complete = cleanup_complete


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    # C5b: the one app version (desktop/src-tauri/tauri.conf.json, read by server.config).
    from server.config import settings
    # The desktop app's server does not serve the API explorer or the schema: they describe every
    # route to anyone on the machine and are not behind the token (C11b, #338 review F6). A dev run keeps them.
    no_api_explorer = {"docs_url": None, "redoc_url": None, "openapi_url": None} if settings.packaged else {}
    app = FastAPI(title="Arslan Server", version=settings.app_version, lifespan=lifespan, **no_api_explorer)

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

    app.add_middleware(security.LocalOnlyWhenUnauthenticatedMiddleware)

    # add_middleware wraps in reverse order → TrustedHost (added last) is outermost,
    # so a foreign Host is rejected before CORS/routing runs. CORS uses an explicit
    # allowlist (dev: the vite dev server, or ARSLAN_ALLOWED_ORIGINS; packaged: none, whatever the
    # environment says) — never '*' with credentials.
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

    from server.api import ssh_nodes as ssh_nodes_api
    app.include_router(ssh_nodes_api.router, prefix="/api/v1")

    from server.api import spawns as spawns_api

    app.include_router(spawns_api.router, prefix="/api/v1")

    # Test-only helper to seed a spawn without going through the build socket.
    # It creates a spawn with NO auth, so gate it twice: it must be explicitly
    # opted in via ARSLAN_TEST_ROUTES=1 AND never register in the desktop app's
    # server — even if the flag leaks into it (defense in depth, P0-3; C11).
    import os

    from server.config import settings as _test_route_settings

    if (
        os.environ.get("ARSLAN_TEST_ROUTES") == "1"
        and not _test_route_settings.packaged
    ):
        _register_test_routes(app)

    from server.api import facts as facts_api

    app.include_router(facts_api.router, prefix="/api/v1")

    from server.api import registry as registry_api

    app.include_router(registry_api.router, prefix="/api/v1")

    from server.api import orchestrator as orchestrator_api

    app.include_router(orchestrator_api.router, prefix="/api/v1")

    from server.api import runs as runs_api

    app.include_router(runs_api.router, prefix="/api/v1")
    from server.api import desktop as desktop_api
    app.include_router(desktop_api.router, prefix="/api/v1")
    from server.api import approvals as approvals_api
    app.include_router(approvals_api.router, prefix="/api/v1")
    from server.api import permissions as permissions_api
    app.include_router(permissions_api.router, prefix="/api/v1")
    from server.api import capabilities as capabilities_api
    app.include_router(capabilities_api.router, prefix="/api/v1")
    from server.api import judgments as judgments_api
    app.include_router(judgments_api.router, prefix="/api/v1")
    from server.api import lessons as lessons_api
    app.include_router(lessons_api.router, prefix="/api/v1")
    from server.api import phone as phone_api
    app.include_router(phone_api.router, prefix="/api/v1")
    from server.api import browser as browser_api
    app.include_router(browser_api.router, prefix="/api/v1")
    from server.api import hands as hands_api  # 0.1.53 Arslan Hands (Mac apps)
    app.include_router(hands_api.router, prefix="/api/v1")

    from server.api import conversations as conversations_api

    app.include_router(conversations_api.router, prefix="/api/v1")

    # 0.1.58 §2–§3: files in Arslan's window (browse, read, open/reveal, a conversation's files).
    from server.api import files as files_api

    app.include_router(files_api.router, prefix="/api/v1")

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
    # 0.1.56: before companion, so "/projects/board" is never read as a project id.
    from server.api import projects as projects_api
    app.include_router(projects_api.router, prefix="/api/v1")
    from server.api import companion as companion_api
    app.include_router(companion_api.router, prefix="/api/v1")
    from server.api import tasks as tasks_api
    app.include_router(tasks_api.router, prefix="/api/v1")
    from server.api import background_jobs as background_jobs_api
    app.include_router(background_jobs_api.router, prefix="/api/v1")
    from server.api import proactive as proactive_api
    app.include_router(proactive_api.router, prefix="/api/v1")
    from server.api import workspace as workspace_api
    app.include_router(workspace_api.router, prefix="/api/v1")
    from server.api import expert_conversion as expert_conversion_api
    app.include_router(expert_conversion_api.router, prefix="/api/v1")
    from server.api import professional_methods as professional_methods_api
    app.include_router(professional_methods_api.router, prefix="/api/v1")

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

    from server.ws.arslan import arslan_endpoint

    @app.websocket("/ws/arslan/{conversation_id}")
    async def _ws_arslan(websocket: WebSocket, conversation_id: str):  # noqa: ANN202
        await arslan_endpoint(websocket, conversation_id)

    from server.ws.bridge import bridge_endpoint

    @app.websocket("/ws/bridge")
    async def _ws_bridge(websocket: WebSocket):  # noqa: ANN202
        await bridge_endpoint(websocket)

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
        # Entry pages: the app, and the island's own page (0.1.51) that the
        # shell's notch window loads. Both name hashed bundles, so neither may
        # be cached — the same stale-frontend bug as below, in a second window.
        entry_pages = {index_file.resolve(), (static_dir / "island.html").resolve()}

        # 🔴 The entry point must never be cached, and this was found on a real
        # upgrade rather than here. Installing over an existing copy left the UI
        # showing the PREVIOUS version's frontend while live API data was current —
        # WebKit had cached index.html heuristically (FileResponse sends etag and
        # last-modified and no Cache-Control), so it kept asking for the OLD hashed
        # bundle, which was also in the cache. Content hashing protects the assets
        # and does nothing for the file that names them. Quitting does not help: the
        # cache is on disk.
        #
        # Worse than stale copy: the previous frontend has no CryptoHealthNotice at
        # all, so an upgrading user whose keys had genuinely broken would see the
        # same silence spec ⓪ exists to end.
        _INDEX_HEADERS = {"Cache-Control": "no-store, must-revalidate"}

        @app.get("/{full_path:path}")
        async def _spa_fallback(full_path: str):  # noqa: ANN202
            # API and WS routes are matched earlier; anything else serves the SPA.
            # Resolve and confirm containment to prevent path traversal
            # (e.g. percent-encoded "../" escaping the static directory).
            if full_path:
                candidate = (static_dir / full_path).resolve()
                if candidate.is_file() and candidate.is_relative_to(static_root):
                    # index.html can also be requested by name, and it is still an
                    # entry point when it is.
                    if candidate in entry_pages:
                        return FileResponse(str(candidate), headers=_INDEX_HEADERS)
                    # Everything else here is a hashed build artefact: leave it
                    # cacheable. Blanket no-store would re-fetch a 2.5 MB bundle on
                    # every launch and call that a fix.
                    return FileResponse(str(candidate))
            return FileResponse(str(index_file), headers=_INDEX_HEADERS)

    return app


def _register_test_routes(app: FastAPI) -> None:
    from fastapi import Depends as _Depends
    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

    from server.db.session import get_session as _get_session
    from server.services import spawn_service as _spawn_service

    # Behind the access token like every other route that writes (C11b, #338 review F7); with no
    # token active (the dev harness) require_auth is a no-op, so the test fixtures are unchanged.
    @app.post("/api/v1/_test/seed_spawn", dependencies=[_Depends(require_auth)])
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
