import dataclasses
from contextlib import asynccontextmanager

import httpx
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server import config
from server.db import session as db_session
from server.db.models import Base
from server.mcp_server import token_store
from server.mcp_server.gate import McpServerGate
from server.mcp_server.server import build_mcp_server
from server.services import settings_service

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "0"}}}
H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


@pytest_asyncio.fixture
async def harness(tmp_path, monkeypatch):
    # isolate the MCP token file to tmp_path.
    # NOTE: server.config.Settings is a frozen dataclass, so
    # monkeypatch.setattr("server.config.settings.data_dir", ...) raises
    # dataclasses.FrozenInstanceError. Rebind the module-level `settings` name
    # itself to a replacement instance instead (same pattern as
    # tests/server/test_mcp_server_gate.py's `env` fixture).
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, data_dir=str(tmp_path)))
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'i.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    mcp = build_mcp_server()
    mcp_app = mcp.streamable_http_app()  # lazily creates session_manager

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():   # drive from parent lifespan (as main.py will)
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/mcp-server", McpServerGate(mcp_app))

    @app.get("/{full_path:path}")               # SPA catch-all AFTER the mount
    async def spa(full_path: str):              # noqa: ANN202
        return JSONResponse({"spa": True})

    async def set_enabled(v):
        async with maker() as s:
            await settings_service.update_settings(s, {"mcp_server_enabled": v})

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as ac:
            yield ac, set_enabled, tmp_path
    await engine.dispose()


async def test_disabled_first_request_is_403(harness):
    ac, set_enabled, tmp = harness
    await set_enabled(False)
    r = await ac.post("/mcp-server/", json=INIT, headers=H)
    assert r.status_code == 403


async def test_enabled_valid_token_initialize_and_list_tools_succeed(harness):
    ac, set_enabled, tmp = harness
    tok = token_store.generate_mcp_token(data_dir=tmp)
    await set_enabled(True)
    auth = {**H, "Authorization": f"Bearer {tok}"}
    r = await ac.post("/mcp-server/", json=INIT, headers=auth)
    assert r.status_code == 200 and "application/json" in r.headers["content-type"]
    tl = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    r2 = await ac.post("/mcp-server/", json=tl, headers=auth)
    names = {t["name"] for t in r2.json()["result"]["tools"]}
    assert names == {"list_spawns", "list_capabilities", "get_run_status"}


async def test_foreign_origin_rejected(harness):
    ac, set_enabled, tmp = harness
    tok = token_store.generate_mcp_token(data_dir=tmp)
    await set_enabled(True)
    r = await ac.post("/mcp-server/", json=INIT,
                      headers={**H, "Authorization": f"Bearer {tok}", "Origin": "http://evil.example"})
    assert r.status_code == 403  # transport_security rejects a foreign Origin


async def test_disable_immediately_rejects_previously_valid_token(harness):
    ac, set_enabled, tmp = harness
    tok = token_store.generate_mcp_token(data_dir=tmp)
    await set_enabled(True)
    auth = {**H, "Authorization": f"Bearer {tok}"}
    assert (await ac.post("/mcp-server/", json=INIT, headers=auth)).status_code == 200
    await set_enabled(False)                         # no restart
    assert (await ac.post("/mcp-server/", json=INIT, headers=auth)).status_code == 403


async def test_rotate_immediately_rejects_old_token(harness):
    ac, set_enabled, tmp = harness
    old = token_store.generate_mcp_token(data_dir=tmp)
    await set_enabled(True)
    token_store.generate_mcp_token(data_dir=tmp)     # rotate
    r = await ac.post("/mcp-server/", json=INIT, headers={**H, "Authorization": f"Bearer {old}"})
    assert r.status_code == 401


async def test_spa_still_served_for_non_mount_path(harness):
    ac, set_enabled, tmp = harness
    await set_enabled(True)
    r = await ac.get("/somewhere-else")
    assert r.status_code == 200 and r.json() == {"spa": True}
