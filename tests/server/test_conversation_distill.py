"""REST API tests for POST /conversations/{id}/distill — manual trigger of the
session-end distill pipeline for one conversation."""
from __future__ import annotations

import importlib

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import (
    ArslanMessage,
    Base,
    ConversationEvent,
    ConversationSpawn,
    Spawn,
)

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
    """The manual endpoint reuses the auto session-end path (distill_service.distill_session):
    only spawns that produced a `spawn_summary` deliverable are distilled, and the returned
    `distilled_spawns` is the honest count of spawns ACTUALLY distilled (NOT the roster size)."""
    cid = "conv-x"
    async with db_session.AsyncSessionLocal() as db:
        db.add(Spawn(id=7, name="Deck Master", domain_category="content",
                     system_prompt="sp", memory_facts=[]))
        db.add(ArslanMessage(conversation_id=cid, role="user", content="帮我出个 deck"))
        db.add(ArslanMessage(conversation_id=cid, role="spawn_summary",
                             content="做完了", display_content="<deck>", spawn_id=7))
        db.add(ConversationSpawn(conversation_id=cid, spawn_id=7, joined_via="routed"))
        await db.commit()

    calls: list[int] = []

    async def _facts(existing, signals):
        return ["用户偏好更简短的输出"]

    from server.services import distill_service
    # Real distill_session runs; stub only the LLM step so no key is needed.
    monkeypatch.setattr(distill_service, "distill_facts", _facts)
    _orig = distill_service._distill_one

    async def _spy(conversation_id, spawn_id):
        calls.append(spawn_id)
        return await _orig(conversation_id, spawn_id)

    monkeypatch.setattr(distill_service, "_distill_one", _spy)

    r = await client.post(f"/api/v1/conversations/{cid}/distill", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    # exactly one producing spawn → count is 1 (not the roster size)
    assert body["distilled_spawns"] == 1

    # only the spawn with a deliverable was attempted
    assert calls == [7]

    # a distill growth event was logged for the conversation recap
    async with db_session.AsyncSessionLocal() as db:
        events = (await db.execute(
            select(ConversationEvent).where(
                ConversationEvent.conversation_id == cid,
                ConversationEvent.kind == "distill"))).scalars().all()
    assert len(events) == 1


async def test_distill_skips_idle_spawns(client, monkeypatch):
    """A roster spawn that produced NOTHING (no `spawn_summary` deliverable) must NOT be
    distilled, and the honest count reflects only producing spawns."""
    cid = "conv-idle"
    async with db_session.AsyncSessionLocal() as db:
        # Spawn 7 produced a deliverable; spawn 8 is on the roster but produced nothing.
        db.add(Spawn(id=7, name="Deck Master", domain_category="content",
                     system_prompt="sp", memory_facts=[]))
        db.add(Spawn(id=8, name="Idle One", domain_category="content",
                     system_prompt="sp", memory_facts=[]))
        db.add(ArslanMessage(conversation_id=cid, role="user", content="帮我出个 deck"))
        db.add(ArslanMessage(conversation_id=cid, role="spawn_summary",
                             content="做完了", display_content="<deck>", spawn_id=7))
        db.add(ConversationSpawn(conversation_id=cid, spawn_id=7, joined_via="routed"))
        db.add(ConversationSpawn(conversation_id=cid, spawn_id=8, joined_via="invited"))
        await db.commit()

    async def _facts(existing, signals):
        return ["用户偏好更简短的输出"]

    from server.services import distill_service
    monkeypatch.setattr(distill_service, "distill_facts", _facts)

    r = await client.post(f"/api/v1/conversations/{cid}/distill", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    # only spawn 7 produced a deliverable → idle spawn 8 is skipped, count is 1
    assert body["distilled_spawns"] == 1

    # spawn 8 was never distilled → no memory_facts written, no idempotency marker
    from server.db.models import DistilledSession
    async with db_session.AsyncSessionLocal() as db:
        idle = await db.get(Spawn, 8)
        assert idle.memory_facts == []
        marks = (await db.execute(
            select(DistilledSession).where(
                DistilledSession.conversation_id == cid,
                DistilledSession.spawn_id == 8))).scalars().all()
    assert marks == []
