"""Task 9: Settings REST API — MCP-token generate/view/disable (localhost-gated).

Mirrors the ``access_token_router`` pattern (server/api/settings.py:32-100), but with
a show-once contract: the full token plaintext is returned ONLY by ``generate``, once.
``GET /settings/mcp-token`` reports only ``{enabled, token_set}`` — never the value.
"""
import importlib

import pytest


@pytest.fixture
async def local_client(tmp_path, monkeypatch):
    # isolate token file + DB to tmp; the shared `client` fixture pattern with a
    # loopback client so _is_direct_localhost passes.
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    monkeypatch.setenv("ARSLAN_TEST_ROUTES", "1")
    import server.config as cfg
    importlib.reload(cfg)

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from server.db.models import Base
    from server.db.session import get_session
    from server.registry.seeder import seed_registry_with
    from server.main import create_app

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'app.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        await seed_registry_with(s)

    async def _override():
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override
    # a loopback client address so _is_direct_localhost() is satisfied
    transport = ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as ac:
        yield ac, tmp_path
    await engine.dispose()


@pytest.fixture
async def remote_client(tmp_path, monkeypatch):
    """Same app/DB setup as local_client, but the ASGI transport reports a
    non-loopback client address — exercises the localhost gate's 403 path."""
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    monkeypatch.setenv("ARSLAN_TEST_ROUTES", "1")
    import server.config as cfg
    importlib.reload(cfg)

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from server.db.models import Base
    from server.db.session import get_session
    from server.registry.seeder import seed_registry_with
    from server.main import create_app

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'app.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        await seed_registry_with(s)

    async def _override():
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override
    # a non-loopback client address: _is_direct_localhost() must reject this.
    transport = ASGITransport(app=app, client=("203.0.113.9", 5555))
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as ac:
        yield ac, tmp_path
    await engine.dispose()


async def test_generate_returns_token_once_and_sets_it(local_client):
    ac, tmp = local_client
    r = await ac.post("/api/v1/settings/mcp-token/generate")
    assert r.status_code == 200
    body = r.json()
    assert body["token"] and body["token_set"] is True and body["enabled"] is False
    from server.mcp_server import token_store
    assert token_store.read_mcp_token(data_dir=tmp) == body["token"]


async def test_generate_rotates(local_client):
    ac, tmp = local_client
    t1 = (await ac.post("/api/v1/settings/mcp-token/generate")).json()["token"]
    t2 = (await ac.post("/api/v1/settings/mcp-token/generate")).json()["token"]
    assert t1 != t2


async def test_view_withholds_token_shown_once_and_disable_clears(local_client):
    ac, tmp = local_client
    gen = (await ac.post("/api/v1/settings/mcp-token/generate")).json()
    assert gen["token"]                                   # shown once, on generate only
    v = (await ac.get("/api/v1/settings/mcp-token")).json()
    assert v["token_set"] is True and v["token"] is None  # GET never re-shows the full token
    d = (await ac.post("/api/v1/settings/mcp-token/disable")).json()
    assert d["token_set"] is False and d["token"] is None
    from server.mcp_server import token_store
    assert token_store.read_mcp_token(data_dir=tmp) == ""


async def test_get_never_returns_token_even_when_unset(local_client):
    """GET before any token exists: token_set False, token always None."""
    ac, tmp = local_client
    v = (await ac.get("/api/v1/settings/mcp-token")).json()
    assert v["token_set"] is False and v["token"] is None and v["enabled"] is False


async def test_generate_forbidden_for_non_localhost(remote_client):
    ac, tmp = remote_client
    r = await ac.post("/api/v1/settings/mcp-token/generate")
    assert r.status_code == 403
    from server.mcp_server import token_store
    assert token_store.read_mcp_token(data_dir=tmp) == ""  # no mint happened


async def test_disable_forbidden_for_non_localhost(remote_client):
    """A token minted out-of-band (e.g. by a prior localhost session) must survive
    a remote caller's attempt to clear it."""
    ac, tmp = remote_client
    from server.mcp_server import token_store
    seeded = token_store.generate_mcp_token(data_dir=tmp)

    r = await ac.post("/api/v1/settings/mcp-token/disable")
    assert r.status_code == 403
    assert token_store.read_mcp_token(data_dir=tmp) == seeded  # still set, unchanged


async def test_get_rejects_forwarded_header_spoof(local_client):
    """A DIRECT loopback connection never carries a forwarding header; its presence
    disqualifies the request even though the reported client host is loopback."""
    ac, tmp = local_client
    r = await ac.post("/api/v1/settings/mcp-token/generate",
                       headers={"X-Forwarded-For": "127.0.0.1"})
    assert r.status_code == 403
