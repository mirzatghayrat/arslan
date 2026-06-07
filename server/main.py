"""FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI

from server.api import health


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    app = FastAPI(title="Arslan Server", version="0.1.0")
    app.include_router(health.router, prefix="/api/v1")
    return app


app = create_app()
