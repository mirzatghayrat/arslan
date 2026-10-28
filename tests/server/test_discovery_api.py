"""The routes left under /discovery (the SKILL.md import panel) sit behind require_auth."""
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'disc.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from server.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    from server.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t"), m


# require_auth reads config.settings at call time; swap in a token-bearing
# Settings (monkeypatch auto-restores) instead of importlib.reload to keep the
# module-level config uncontaminated for sibling tests.


async def test_discovery_requires_auth_when_token_set(tmp_path, monkeypatch):
    import dataclasses

    import server.config as config
    from server.db.models import Base
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'disc_auth.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:  # already inside an async test -> await, no anyio.run
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    monkeypatch.setattr(config, "settings",
                        dataclasses.replace(config.settings, api_token="secret-tok"))
    from server.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/discovery/skills/scan", json={"ref": "not a repo"})
    assert r.status_code in (401, 403)
    await engine.dispose()


async def test_discovery_open_when_token_unset(client):
    c, m = client  # fixture leaves ARSLAN_API_TOKEN="" -> require_auth is a no-op
    async with c:
        r = await c.post("/api/v1/discovery/skills/scan", json={"ref": "not a repo"})
    assert r.status_code == 400          # reached the handler: a bad ref, not an auth refusal
