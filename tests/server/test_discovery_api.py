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


async def test_search_endpoint(client, monkeypatch):
    c, m = client
    from server.services import github_eval
    async def fake_search(q): return [{"full_name": "o/a", "html_url": "h", "stars": 1500, "forks": 1,
        "license": "MIT", "pushed_days": 5, "description": "d", "trust": {"tier": "high", "license_note": "MIT: commercial-safe"}}]
    monkeypatch.setattr(github_eval, "search_repos", fake_search)
    async with c:
        r = await c.get("/api/v1/discovery/search", params={"q": "mcp"})
    assert r.status_code == 200
    body = r.json()
    assert body[0]["full_name"] == "o/a" and body[0]["trust"]["tier"] == "high"


async def test_search_empty_400(client, monkeypatch):
    c, m = client
    from server.services import github_eval
    async def boom(q): raise ValueError("query required")
    monkeypatch.setattr(github_eval, "search_repos", boom)
    async with c:
        r = await c.get("/api/v1/discovery/search", params={"q": "  "})
    assert r.status_code == 400


async def test_catalog_save_list_delete(client, monkeypatch):
    c, m = client
    snap = {"repo": {"full_name": "o/r", "html_url": "u", "stars": 9}, "trust": {"tier": "low"}, "suggestion": {"is_mcp": False}}
    async with c:
        saved = (await c.post("/api/v1/discovery/catalog", json={"snapshot": snap})).json()
        listed = (await c.get("/api/v1/discovery/catalog")).json()
        d = await c.delete(f"/api/v1/discovery/catalog/{saved['id']}")
        after = (await c.get("/api/v1/discovery/catalog")).json()
    assert any(x["full_name"] == "o/r" for x in listed)
    assert d.status_code == 200 and after == []


async def test_catalog_refresh(client, monkeypatch):
    c, m = client
    from server.services import discovery_service
    async def fake_eval(owner, repo): return {"repo": {"full_name": f"{owner}/{repo}", "html_url": "u", "stars": 999},
        "trust": {"tier": "high"}, "suggestion": {"is_mcp": True}}
    monkeypatch.setattr(discovery_service, "evaluate_ref", fake_eval)
    snap = {"repo": {"full_name": "o/r", "html_url": "u", "stars": 9}, "trust": {"tier": "low"}, "suggestion": {"is_mcp": False}}
    async with c:
        saved = (await c.post("/api/v1/discovery/catalog", json={"snapshot": snap})).json()
        refreshed = (await c.post(f"/api/v1/discovery/catalog/{saved['id']}/refresh")).json()
    assert refreshed["snapshot"]["trust"]["tier"] == "high"


async def test_catalog_refresh_404(client):
    c, m = client
    async with c:
        r = await c.post("/api/v1/discovery/catalog/9999/refresh")
    assert r.status_code == 404


async def test_skill_generate_endpoint(client, monkeypatch):
    c, m = client
    from server.services import discovery_service
    async def fake_draft(owner, repo): return {"repo": {"full_name": f"{owner}/{repo}", "html_url": "u"},
        "skill": {"name": "T", "category": "research", "description": "d", "body": "## Trigger\nx\n## 决策规则\ny"}}
    monkeypatch.setattr(discovery_service, "generate_skill_draft", fake_draft)
    async with c:
        r = await c.post("/api/v1/discovery/skill/generate", json={"ref": "o/r"})
    assert r.status_code == 200 and r.json()["skill"]["name"] == "T"


async def test_skill_generate_bad_ref_400(client):
    c, m = client
    async with c:
        r = await c.post("/api/v1/discovery/skill/generate", json={"ref": "not a repo"})
    assert r.status_code == 400


async def test_skill_create_endpoint(client):
    c, m = client
    body = "## Trigger\nx\n## 决策规则\ny"
    async with c:
        r = await c.post("/api/v1/discovery/skill", json={"full_name": "o/r", "name": "My Tech",
            "category": "research", "description": "d", "body": body})
        created = r.json()
    assert r.status_code == 200 and created["key"].startswith("gh-")
    assert created["tier"] == "safe" and created["status"] == "registered"


async def test_skill_create_missing_sections_400(client):
    c, m = client
    async with c:
        r = await c.post("/api/v1/discovery/skill", json={"full_name": "o/r", "name": "n",
            "category": "c", "description": "d", "body": "no sections"})
    assert r.status_code == 400


# --- auth gating (discovery surfaces MCP/skill candidates) ------------------
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
        r = await c.get("/api/v1/discovery/catalog")
    assert r.status_code in (401, 403)
    await engine.dispose()


async def test_discovery_open_when_token_unset(client):
    c, m = client  # fixture leaves ARSLAN_API_TOKEN="" -> require_auth is a no-op
    async with c:
        r = await c.get("/api/v1/discovery/catalog")
    assert r.status_code == 200
