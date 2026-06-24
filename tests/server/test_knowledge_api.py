"""REST API tests for per-spawn knowledge base: ingest (text + file), list, delete."""
from __future__ import annotations

import importlib

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
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


async def _spawn(client) -> int:
    async with client.db_maker() as db:
        s = Spawn(name="S", domain_category="x", system_prompt="p")
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


async def test_post_text_then_list_then_delete(client):
    sid = await _spawn(client)
    r = await client.post(
        f"/api/v1/spawns/{sid}/knowledge",
        json={"source": "policy", "text": "refund within 30 days " * 50},
    )
    assert r.status_code == 200 and r.json()["chunks_added"] >= 1

    r = await client.get(f"/api/v1/spawns/{sid}/knowledge")
    assert r.status_code == 200
    assert any(item["source"] == "policy" for item in r.json())

    r = await client.delete(f"/api/v1/spawns/{sid}/knowledge", params={"source": "policy"})
    assert r.status_code == 200 and r.json()["deleted"] >= 1


async def test_post_file_upload(client):
    sid = await _spawn(client)
    files = {"file": ("notes.txt", b"hello knowledge", "text/plain")}
    r = await client.post(f"/api/v1/spawns/{sid}/knowledge", files=files)
    assert r.status_code == 200 and r.json()["chunks_added"] == 1


async def test_post_unsupported_file_400(client):
    sid = await _spawn(client)
    files = {"file": ("img.png", b"\x89PNG", "image/png")}
    r = await client.post(f"/api/v1/spawns/{sid}/knowledge", files=files)
    assert r.status_code == 400


async def test_post_url_ingests(client, monkeypatch):
    sid = await _spawn(client)
    captured = {}

    async def fake_ingest_url(spawn_id, url, *, compress=False):
        captured["spawn_id"] = spawn_id
        captured["url"] = url
        captured["compress"] = compress
        return 3

    monkeypatch.setattr("server.api.knowledge.ingest.ingest_url", fake_ingest_url)
    r = await client.post(
        f"/api/v1/spawns/{sid}/knowledge",
        json={"url": "https://example.com", "compress": True},
    )
    assert r.status_code == 200
    assert r.json()["chunks_added"] == 3
    assert captured["compress"] is True


async def test_post_url_private_rejected_400(client):
    sid = await _spawn(client)
    r = await client.post(
        f"/api/v1/spawns/{sid}/knowledge",
        json={"url": "http://169.254.169.254/latest/meta-data/"},
    )
    assert r.status_code == 400


async def test_post_text_compress_passthrough(client, monkeypatch):
    sid = await _spawn(client)
    captured = {}

    async def fake_ingest_text(spawn_id, source, text, *, compress=False):
        captured["compress"] = compress
        return 1

    monkeypatch.setattr("server.api.knowledge.ingest.ingest_text", fake_ingest_text)
    r = await client.post(
        f"/api/v1/spawns/{sid}/knowledge",
        json={"source": "s", "text": "t", "compress": True},
    )
    assert r.status_code == 200
    assert captured["compress"] is True
