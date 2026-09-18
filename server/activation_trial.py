"""Internal restricted trial ASGI app; no normal application routes/backgrounds.

The native process launcher is not wired yet. A prepared dedicated process must
already have loaded its original key/configuration; this factory never imports
configuration to bootstrap a new secret. A healthy trial is not finalization.
"""
from contextlib import asynccontextmanager
from pathlib import Path
import re
import secrets
import sys

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from server.services.profile_activation import trial_ownership
from server.services.storage_boot import initialize


def create_app(active: Path, operation_id: str, access_token: str) -> FastAPI:
    active = active.absolute()
    if not isinstance(access_token, str) or not re.fullmatch(r"[0-9a-f]{64}", access_token):
        raise ValueError("activation_trial_token_invalid")
    config = sys.modules.get("server.config")
    if config is None:
        raise ValueError("activation_trial_runtime_not_prepared")

    @asynccontextmanager
    async def lifespan(app):
        if (Path(config.settings.db_path).resolve() != (active / "arslan.db").resolve()
                or Path(config.settings.data_dir).resolve() != active.resolve()):
            raise ValueError("activation_trial_configuration_mismatch")
        from server.db.session import build_engine

        with trial_ownership(active, operation_id, config.settings.secret_key):
            from server.main import _validate_settings
            _validate_settings(config.settings, active_token=access_token)
            # Do not reuse the normal application's global engine/session pool.
            engine = build_engine(f"sqlite+aiosqlite:///{active / 'arslan.db'}")
            try:
                await initialize(engine)
                app.state.ready = True
                yield
            finally:
                app.state.ready = False
                await engine.dispose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ready = False

    @app.get("/api/v1/activation-trial/health")
    async def health(authorization: str | None = Header(default=None)):
        if not secrets.compare_digest((authorization or "").encode(), f"Bearer {access_token}".encode()):
            raise HTTPException(status_code=401, detail="unauthorized")
        if not app.state.ready:
            raise HTTPException(status_code=503, detail="not_ready")
        return JSONResponse({"status": "ready", "mode": "activation_trial", "operation_id": operation_id},
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    return app
