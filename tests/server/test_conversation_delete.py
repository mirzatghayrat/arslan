"""REST API tests for DELETE /conversations/{id} — purge a conversation's OWN
rows while deliberately KEEPING runs + router_decisions (audit/diagnosis data)."""
from __future__ import annotations

import importlib

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import (
    ArslanMessage,
    Base,
    ConversationEvent,
    RouterDecision,
    Run,
)
from server.services import permission_store

AUTH = {"Authorization": "Bearer test-token"}


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_API_TOKEN", "test-token")
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "delete.db"))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))

    import server.config as config

    importlib.reload(config)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'delete.db'}")
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


async def test_delete_requires_auth(client):
    r = await client.delete("/api/v1/conversations/conv-x")
    assert r.status_code in (401, 403)


async def test_delete_purges_own_rows_keeps_runs(client):
    cid = "conv-x"
    async with db_session.AsyncSessionLocal() as db:
        db.add(ArslanMessage(conversation_id=cid, role="user", content="hi"))
        db.add(ArslanMessage(conversation_id=cid, role="arslan", content="hello"))
        db.add(ConversationEvent(conversation_id=cid, kind="distill", summary="grew"))
        db.add(Run(conversation_id=cid, user_message="hi", status="recorded"))
        db.add(RouterDecision(conversation_id=cid, user_message="hi", action="answer"))
        await db.commit()

    r = await client.delete(f"/api/v1/conversations/{cid}", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    deleted = body["deleted"]
    assert deleted["arslan_messages"] >= 1
    assert deleted["conversation_events"] >= 1

    async with db_session.AsyncSessionLocal() as db:
        async def _count(model):
            return (await db.execute(
                select(func.count()).select_from(model).where(
                    model.conversation_id == cid))).scalar_one()

        # OWN rows purged
        assert await _count(ArslanMessage) == 0
        assert await _count(ConversationEvent) == 0
        # audit/diagnosis rows deliberately KEPT
        assert await _count(Run) == 1
        assert await _count(RouterDecision) == 1


async def test_delete_drops_the_conversations_permission_grants_and_keeps_the_ledger(client):
    """0.1.61 §A5: grants live as long as their conversation. The ledger (§A8) keeps its 90 days."""
    cid, other = "conv-x", "conv-y"
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_grant(db, cid, "", "schedule", "*")                  # conversation
        await permission_store.add_grant(db, cid, "turn-a", "app", "com.apple.Notes")   # one task
        await permission_store.add_grant(db, other, "", "schedule", "*")
        await permission_store.record(db, conversation_id=cid, kind="app", target="com.apple.Notes",
                                      mode="standard", decided_by="grant", decision="allow",
                                      scope="task")
        await db.commit()

    r = await client.delete(f"/api/v1/conversations/{cid}", headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"]["permission_grants"] == 2

    async with db_session.AsyncSessionLocal() as db:
        assert await permission_store.find_grant(db, cid, "turn-a", "app", "com.apple.Notes") is None
        assert await permission_store.find_grant(db, cid, "turn-z", "schedule", "*") is None
        assert await permission_store.find_grant(db, other, "turn-z", "schedule", "*")   # not theirs
        assert [e.target for e in await permission_store.recent(db)] == ["com.apple.Notes"]
