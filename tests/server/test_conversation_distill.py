"""REST API tests for POST /conversations/{id}/distill — manual trigger of the
session-end distill pipeline for one conversation."""
from __future__ import annotations

import importlib

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import ArslanMessage, Base, ConversationEvent, ConversationSpawn

AUTH = {"Authorization": "Bearer test-token"}


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_API_TOKEN", "test-token")
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "distill.db"))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))

    import server.config as config

    importlib.reload(config)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'distill.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await engine.dispose()


async def test_distill_requires_auth(client):
    r = await client.post("/api/v1/conversations/conv-x/distill")
    assert r.status_code in (401, 403)


async def test_distill_returns_counts(client, monkeypatch):
    cid = "conv-x"
    async with db_session.AsyncSessionLocal() as db:
        db.add(ArslanMessage(conversation_id=cid, role="user", content="帮我出个 deck"))
        db.add(ArslanMessage(conversation_id=cid, role="spawn_summary",
                             content="做完了", display_content="<deck>", spawn_id=7))
        db.add(ConversationSpawn(conversation_id=cid, spawn_id=7, joined_via="routed"))
        await db.commit()

    calls: list[tuple[int, str]] = []

    async def _stub(spawn_id, signals):
        calls.append((spawn_id, signals))
        return 1  # truthy

    from server.services import distill_service
    monkeypatch.setattr(distill_service, "distill_from_signals", _stub)

    r = await client.post(f"/api/v1/conversations/{cid}/distill", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["distilled_spawns"] >= 1

    # distill_from_signals was invoked once per participating spawn
    assert [c[0] for c in calls] == [7]

    # a distill growth event was logged for the conversation recap
    async with db_session.AsyncSessionLocal() as db:
        events = (await db.execute(
            select(ConversationEvent).where(
                ConversationEvent.conversation_id == cid,
                ConversationEvent.kind == "distill"))).scalars().all()
    assert len(events) == 1
