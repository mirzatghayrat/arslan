"""REST API tests for fact CRUD (Settings -> Memory), on memory v2: edits and deletes name the version."""
from __future__ import annotations

import importlib

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from tests.server.conftest import boot_schema

AUTH = {"Authorization": "Bearer test-token"}


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_API_TOKEN", "test-token")
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "facts.db"))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))

    import server.config as config

    importlib.reload(config)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'facts.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(boot_schema)  # as a launch leaves it: memory v2 (C2a)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await engine.dispose()


async def test_facts_crud_roundtrip(client):
    r = await client.get("/api/v1/facts", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == []

    r = await client.post("/api/v1/facts", headers=AUTH, json={"content": "I prefer metric units"})
    assert r.status_code == 201
    fact = r.json()
    assert fact["content"] == "I prefer metric units"
    assert fact["source"] == "manual"
    fid = fact["id"]

    r = await client.get("/api/v1/facts", headers=AUTH)
    assert len(r.json()) == 1

    r = await client.put(f"/api/v1/facts/{fid}", headers=AUTH, json={"content": "I prefer imperial units"})
    assert r.status_code == 428                         # no version named

    r = await client.put(
        f"/api/v1/facts/{fid}", headers=AUTH,
        json={"content": "I prefer imperial units", "sensitive": True, "expected_version": fact["version"]}
    )
    assert r.status_code == 200
    edited = r.json()
    assert edited["content"] == "I prefer imperial units"
    assert edited["sensitive"] is True

    r = await client.delete(f"/api/v1/facts/{fid}?expected_version={fact['version']}", headers=AUTH)
    assert r.status_code == 409                         # an older version

    r = await client.delete(f"/api/v1/facts/{fid}?expected_version={edited['version']}", headers=AUTH)
    assert r.status_code == 204

    r = await client.get("/api/v1/facts", headers=AUTH)
    assert r.json() == []


async def test_facts_requires_auth(client):
    r = await client.get("/api/v1/facts")
    assert r.status_code in (401, 403)


async def test_update_missing_fact_404(client):
    r = await client.put("/api/v1/facts/999", headers=AUTH, json={"content": "x", "expected_version": 1})
    assert r.status_code == 404


async def test_delete_missing_fact_404(client):
    r = await client.delete("/api/v1/facts/999?expected_version=1", headers=AUTH)
    assert r.status_code == 404


async def test_create_blank_fact_rejected(client):
    r = await client.post("/api/v1/facts", headers=AUTH, json={"content": "   "})
    assert r.status_code == 422
