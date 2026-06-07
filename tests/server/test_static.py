"""Static SPA serving + unknown-route fallback."""
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base
from server.db.session import get_session


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    # Create a fake built frontend.
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html><title>Arslan</title>")
    (static_dir / "assets").mkdir()
    (static_dir / "assets" / "app.js").write_text("console.log('hi')")

    monkeypatch.setenv("ARSLAN_STATIC_DIR", str(static_dir))
    import importlib

    import server.config as config

    importlib.reload(config)
    from server.main import create_app

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'st.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override():
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await engine.dispose()


@pytest.mark.asyncio
async def test_serves_index_at_root(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Arslan" in resp.text


@pytest.mark.asyncio
async def test_spa_fallback_for_client_route(client):
    resp = await client.get("/chat/5")
    assert resp.status_code == 200
    assert "Arslan" in resp.text  # index.html, not 404


@pytest.mark.asyncio
async def test_api_404_still_json(client):
    resp = await client.get("/api/v1/spawns/12345")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_path_traversal_is_blocked(client):
    # Percent-encoded ../ must NOT escape the static dir; it falls back to index.
    resp = await client.get("/%2e%2e/%2e%2e/%2e%2e/etc/hosts")
    assert resp.status_code == 200
    assert "Arslan" in resp.text  # served index.html, NOT /etc/hosts
    assert "localhost" not in resp.text


@pytest.mark.asyncio
async def test_serves_real_static_asset(client):
    resp = await client.get("/assets/app.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text
