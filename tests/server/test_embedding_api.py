"""Embedding ops endpoints: status, reindex trigger, local model download."""
from __future__ import annotations

import importlib

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.migrations.versions._0009_knowledge import upgrade_sync
from server.db.models import Base


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


async def test_status_shape(client):
    r = await client.get("/api/v1/embedding/status")
    assert r.status_code == 200
    body = r.json()
    assert {"provider", "model", "embedded", "pending", "reindex", "local_model"} <= set(body)
    assert body["provider"] is None  # test DB has no provider config
    assert body["local_model"]["status"] in ("absent", "ready", "downloading", "error")


async def test_reindex_returns_accepted(client):
    r = await client.post("/api/v1/embedding/reindex")
    assert r.status_code == 200
    assert r.json()["started"] in (True, False)  # no provider → False, never crashes


async def test_pending_reflects_stale_model_after_switch(client, monkeypatch):
    """With an active provider, 'pending' counts the real embed_missing backlog
    (NULL or stale-model), not just NULL — so a model switch honestly shows work
    remaining even though every row already has *some* vector."""
    from sqlalchemy import text as sa_text

    from server.db.models import Spawn
    from server.services import embedding_service

    async with client.db_maker() as s:
        s.add(Spawn(id=1, name="s", domain_category="c", system_prompt="p"))
        await s.flush()
        # Two rows already embedded under the OLD model, one never embedded.
        await s.execute(sa_text(
            "INSERT INTO knowledge_chunks (spawn_id, source, chunk_index, text, embedding, embedding_model) "
            "VALUES (1,'a',0,'x',:b,'old-model'), (1,'a',1,'y',:b,'old-model'), (1,'a',2,'z',NULL,NULL)"),
            {"b": b"\x00\x00\x80?"})
        await s.commit()

    class NewProvider:
        model_id = "new-model"
        async def embed(self, texts):  # pragma: no cover — status path doesn't embed
            return [[0.0] for _ in texts]

    async def _fake_active():
        return NewProvider()
    monkeypatch.setattr(embedding_service, "active_provider", _fake_active)

    body = (await client.get("/api/v1/embedding/status")).json()
    assert body["model"] == "new-model"
    assert body["embedded"] == 2          # naive NOT-NULL count
    assert body["pending"] == 3           # all 3 need (re)embedding under new-model


async def test_download_model_kicks_state(client, monkeypatch):
    from server.services import local_embedding as le
    # Isolate the module-level state dict to this test so the fake download's
    # mutation doesn't leak into other test files sharing this process.
    monkeypatch.setattr(le, "_state", dict(le._state), raising=False)
    async def fake_dl():
        le._state.update(status="downloading", error=None)
    monkeypatch.setattr(le, "download_local_model", fake_dl)
    r = await client.post("/api/v1/embedding/download-model")
    assert r.status_code == 200
    body = r.json()
    assert body["started"] is True
    # Prove the response carries the download-status contract (a synchronous
    # read): {status: {status: <enum>, error: ...}}.
    assert body["status"]["status"] in ("absent", "downloading", "ready", "error")
    assert "error" in body["status"]
