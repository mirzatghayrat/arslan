"""FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI

from server.api import health


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    from fastapi import Depends

    from server.auth import require_auth

    app = FastAPI(title="Arslan Server", version="0.1.0")
    app.include_router(health.router, prefix="/api/v1")

    @app.get("/api/v1/_authcheck", dependencies=[Depends(require_auth)])
    async def _authcheck() -> dict[str, bool]:
        return {"ok": True}

    return app


app = create_app()
