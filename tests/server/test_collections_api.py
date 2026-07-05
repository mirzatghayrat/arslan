"""Collections CRUD + ingest + spawn binding endpoints."""
from __future__ import annotations

import importlib

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.migrations.versions._0009_knowledge import upgrade_sync
from server.db.models import Base, Spawn


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """Async HTTP client backed by an in-memory SQLite DB with FTS5 set up."""
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "kb.db"))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    monkeypatch.setenv("ARSLAN_TEST_ROUTES", "1")

    import server.config as config

    importlib.reload(config)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(upgrade_sync)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.db_maker = maker  # type: ignore[attr-defined]
        yield c
    await engine.dispose()


async def _mk_spawn(client, sid=1):
    async with client.db_maker() as s:
        s.add(Spawn(id=sid, name=f"s{sid}", domain_category="c", system_prompt="p"))
        await s.commit()


async def test_collection_crud_and_ingest(client):
    r = await client.post("/api/v1/collections", json={"name": "保险资料", "description": "合同们"})
    assert r.status_code == 200
    cid = r.json()["id"]

    r = await client.post(f"/api/v1/collections/{cid}/ingest",
                          json={"source": "条款.txt", "text": "第三条:报销上限五百元"})
    assert r.status_code == 200 and r.json()["chunks_added"] >= 1

    r = await client.get("/api/v1/collections")
    body = r.json()
    assert body[0]["name"] == "保险资料" and body[0]["chunks"] >= 1

    r = await client.get(f"/api/v1/collections/{cid}/knowledge")
    assert r.json()[0]["source"] == "条款.txt"

    r = await client.patch(f"/api/v1/collections/{cid}", json={"name": "保险库"})
    assert r.status_code == 200 and r.json()["name"] == "保险库"

    r = await client.delete(f"/api/v1/collections/{cid}/knowledge", params={"source": "条款.txt"})
    assert r.json()["deleted"] >= 1
    async with client.db_maker() as s:
        n = (await s.execute(sa_text(
            "SELECT COUNT(*) FROM knowledge_chunks_fts WHERE knowledge_chunks_fts MATCH '五百元'"
        ))).scalar_one()
        assert n == 0  # FTS 同步清理,无孤儿


async def test_bind_unbind_spawn(client):
    await _mk_spawn(client, 1)
    cid = (await client.post("/api/v1/collections", json={"name": "库"})).json()["id"]
    r = await client.put(f"/api/v1/spawns/1/collections/{cid}")
    assert r.status_code == 200
    r = await client.get("/api/v1/collections")
    assert r.json()[0]["spawn_ids"] == [1]
    r = await client.put(f"/api/v1/spawns/1/collections/{cid}")  # 幂等
    assert r.status_code == 200
    r = await client.delete(f"/api/v1/spawns/1/collections/{cid}")
    assert r.status_code == 200
    assert (await client.get("/api/v1/collections")).json()[0]["spawn_ids"] == []


async def test_bind_nonexistent_spawn_404_no_orphan(client):
    cid = (await client.post("/api/v1/collections", json={"name": "库"})).json()["id"]
    r = await client.put(f"/api/v1/spawns/9999/collections/{cid}")
    assert r.status_code == 404
    body = (await client.get("/api/v1/collections")).json()
    assert body[0]["spawn_ids"] == []  # 无孤儿绑定


async def test_delete_collection_cascades(client):
    cid = (await client.post("/api/v1/collections", json={"name": "临时"})).json()["id"]
    await client.post(f"/api/v1/collections/{cid}/ingest", json={"source": "x", "text": "独特词汇烎"})
    r = await client.delete(f"/api/v1/collections/{cid}")
    assert r.status_code == 200
    async with client.db_maker() as s:
        n = (await s.execute(sa_text("SELECT COUNT(*) FROM knowledge_chunks"))).scalar_one()
        assert n == 0
        n = (await s.execute(sa_text(
            "SELECT COUNT(*) FROM knowledge_chunks_fts WHERE knowledge_chunks_fts MATCH '烎'"
        ))).scalar_one()
        assert n == 0
