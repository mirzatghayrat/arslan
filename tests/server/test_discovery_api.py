import anyio
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'disc.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        from server.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    anyio.run(_seed)
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    from server.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t"), m


async def test_evaluate_returns_shape(client, monkeypatch):
    c, m = client
    from server.services import github_eval, mcp_suggest
    async def fake_repo(o, r): return {"full_name": "o/r", "html_url": "u", "stars": 1500,
        "forks": 9, "license": "MIT", "pushed_days": 20, "description": "mcp srv", "topics": ["mcp"]}
    async def fake_readme(o, r): return "npx -y @scope/x"
    async def fake_suggest(meta, readme): return {"is_mcp": True, "transport": "stdio",
        "command": "npx", "args": ["-y", "@scope/x"], "url": None, "reason": "npx"}
    monkeypatch.setattr(github_eval, "fetch_repo", fake_repo)
    monkeypatch.setattr(github_eval, "fetch_readme", fake_readme)
    monkeypatch.setattr(mcp_suggest, "classify_and_suggest", fake_suggest)
    async with c:
        r = await c.post("/api/v1/discovery/evaluate", json={"ref": "o/r"})
    assert r.status_code == 200
    body = r.json()
    assert body["repo"]["stars"] == 1500
    assert body["trust"]["tier"] == "high"            # 1500★ + 20d
    assert "commercial" in body["trust"]["license_note"].lower()
    assert body["suggestion"]["is_mcp"] is True and body["suggestion"]["command"] == "npx"


async def test_evaluate_bad_ref_400(client):
    c, m = client
    async with c:
        r = await c.post("/api/v1/discovery/evaluate", json={"ref": "not a repo"})
    assert r.status_code == 400


async def test_evaluate_persists_nothing(client, monkeypatch):
    c, m = client
    from server.services import github_eval, mcp_suggest
    async def fake_repo(o, r): return {"full_name": "o/r", "html_url": "u", "stars": 10, "forks": 0,
        "license": None, "pushed_days": 9, "description": "", "topics": []}
    monkeypatch.setattr(github_eval, "fetch_repo", fake_repo)
    monkeypatch.setattr(github_eval, "fetch_readme", lambda o, r: _empty())
    monkeypatch.setattr(mcp_suggest, "classify_and_suggest", lambda meta, readme: _no_mcp())
    async with c:
        await c.post("/api/v1/discovery/evaluate", json={"ref": "o/r"})
    async with m() as s:
        # no mcp_servers row was created by evaluate (discovery layer is read-only)
        from sqlalchemy import select
        from server.db.models import MCPServer
        rows = (await s.execute(select(MCPServer))).scalars().all()
    assert rows == []


async def _empty(): return ""
async def _no_mcp(): return {"is_mcp": False, "transport": None, "command": None, "args": [], "url": None, "reason": "x"}
