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
    """Create tables and prune stale build sessions on startup."""
    from datetime import datetime, timedelta
    from pathlib import Path

    from sqlalchemy import delete

    from server.config import settings
    from server.db.models import BuildSession
    from server.db.session import AsyncSessionLocal

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

    from server.registry.seeder import seed_registry

    await seed_registry()

    cutoff = datetime.utcnow() - timedelta(hours=24)
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(BuildSession).where(BuildSession.updated_at < cutoff)
        )
        await db.commit()
    yield

    from server.mcp.session import manager as _mcp_manager
    await _mcp_manager.aclose_all()


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

    from server.api import facts as facts_api

    app.include_router(facts_api.router, prefix="/api/v1")

    from server.api import registry as registry_api

    app.include_router(registry_api.router, prefix="/api/v1")

    from server.api import create as create_api

    app.include_router(create_api.router, prefix="/api/v1")

    from server.api import orchestrator as orchestrator_api

    app.include_router(orchestrator_api.router, prefix="/api/v1")

    from server.api import runs as runs_api

    app.include_router(runs_api.router, prefix="/api/v1")

    from server.api import knowledge as knowledge_api

    app.include_router(knowledge_api.router, prefix="/api/v1")

    from server.api.extract import router as extract_router

    app.include_router(extract_router)

    from server.api.mcp import router as mcp_router

    app.include_router(mcp_router, prefix="/api/v1")

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

    from server.ws.arslan import arslan_endpoint

    @app.websocket("/ws/arslan/{conversation_id}")
    async def _ws_arslan(websocket: WebSocket, conversation_id: str):  # noqa: ANN202
        await arslan_endpoint(websocket, conversation_id)

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
