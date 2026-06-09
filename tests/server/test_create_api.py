"""REST API tests for manual NL spawn creation (draft + create)."""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base

AUTH = {"Authorization": "Bearer test-token"}


@pytest_asyncio.fixture
async def create_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_API_TOKEN", "test-token")
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "create.db"))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))

    import server.config as config

    importlib.reload(config)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'create.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield SimpleNamespace(client=c, AUTH=AUTH)
    await engine.dispose()


async def test_draft_endpoint_returns_draft(create_env, monkeypatch):
    from server.services import spawn_drafter

    async def fake_draft(description, *, previous=None):
        return {"name": "eq", "domain": "finance.equity-research", "capabilities": ["research"]}

    monkeypatch.setattr(spawn_drafter, "draft_from_text", fake_draft)
    r = await create_env.client.post(
        "/api/v1/spawns/draft",
        headers=create_env.AUTH,
        json={"description": "stock fundamentals helper"},
    )
    assert r.status_code == 200
    assert r.json()["domain"] == "finance.equity-research"


async def test_create_endpoint_creates_spawn(create_env):
    body = {
        "name": "eq",
        "domain": "finance.equity-research",
        "capabilities": ["research"],
        "persona_role": "analyst",
        "persona_tone": "rigorous",
    }
    r = await create_env.client.post("/api/v1/spawns", headers=create_env.AUTH, json=body)
    assert r.status_code == 201
    out = r.json()
    assert out["name"] == "eq"
    assert out["domain"] == "finance.equity-research"  # category.subcategory recomposed
    assert out["system_prompt"]  # non-empty persona prompt, not GENERIC
    assert "analyst" in out["system_prompt"]


async def test_create_requires_auth(create_env):
    r = await create_env.client.post(
        "/api/v1/spawns", json={"name": "x", "domain": "y", "capabilities": []}
    )
    assert r.status_code in (401, 403)
