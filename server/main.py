"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, WebSocket

from server.api import health, settings as settings_api
from server.auth import require_auth
from server.db.models import Base
from server.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup (idempotent; complements Alembic in prod)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    app = FastAPI(title="Arslan Server", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(settings_api.router, prefix="/api/v1")

    from server.api import spawns as spawns_api

    app.include_router(spawns_api.router, prefix="/api/v1")

    # Test-only helper to seed a spawn without going through the build socket.
    import os

    if os.environ.get("ARSLAN_TEST_ROUTES") == "1":
        _register_test_routes(app)

    from server.api import templates as templates_api

    app.include_router(templates_api.router, prefix="/api/v1")

    from server.api import evolution as evolution_api

    app.include_router(evolution_api.router, prefix="/api/v1")

    @app.get("/api/v1/_authcheck", dependencies=[Depends(require_auth)])
    async def _authcheck() -> dict[str, bool]:
        return {"ok": True}

    from server.ws.build import build_endpoint

    @app.websocket("/ws/build/{session_id}")
    async def _ws_build(websocket: WebSocket, session_id: str):  # noqa: ANN202
        await build_endpoint(websocket, session_id)

    from server.ws.chat import chat_endpoint

    @app.websocket("/ws/chat/{spawn_id}")
    async def _ws_chat(websocket: WebSocket, spawn_id: int):  # noqa: ANN202
        await chat_endpoint(websocket, spawn_id)

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
