"""An image the model refuses reaches the user as actionable copy.

This file used to cover how a spawn saw the images of the turn it was dispatched
for (dispatcher.with_images). The dispatcher went in C7b-4 (v0.1.63); the one test
that exercises the live path — a user's image on an Arslan turn — stays.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base

IMAGE = {"name": "shot.png", "mime_type": "image/png", "data": "QUJD"}


@pytest_asyncio.fixture
async def image_db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'sv.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(text)")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    yield maker
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_refusal_reaches_the_user_as_actionable_copy(image_db, monkeypatch):
    """The conversion must be WIRED, not merely implemented. A pure function
    nobody calls passes its own unit tests perfectly — that exact shape has bitten
    this round twice already."""
    # 0.1.63 (C1): rewritten from the expert dispatch to an Arslan turn, the only
    # place a user's image now reaches a model.
    from server.orchestrator import arslan as arslan_mod, tool_loop
    from tests.server.conftest import MockAdapter

    refusal = RuntimeError(
        "Error code: 400 - {'error': {'message': \"image_url is only supported "
        "by certain models\", 'type': 'invalid_request_error'}}")
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: MockAdapter(raise_on_call=refusal))
    events: list[dict] = []

    await arslan_mod.handle_user_message("c1", "read this", events.append, images=[IMAGE])
    errors = [e for e in events if e.get("type") == "error"]
    assert errors, "no error surfaced at all"
    msg = errors[-1]["message"]
    assert "image support" in msg, f"raw provider error leaked: {msg[:120]}"
    assert "Error code: 400" not in msg
