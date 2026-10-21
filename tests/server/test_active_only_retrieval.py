"""#12 hermetic regression: retrieval with record_usage=False writes zero brain_usage rows (S2 E3, a replay
must not mutate the Second Brain's usage counters).

0.1.63 C2a and C2a-2 removed this file's v1 tests (superseded_by scans on user_facts and learnings, the 心得
route, POST /facts/dedup's backfill): every launch runs memory v2, and that code is gone. The regression below
runs on memory v2's retrieval scope, the turn project's collections.
"""
from __future__ import annotations

import datetime as dt

import pytest_asyncio
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.services import personal_context as pc

from .v2_retrieval import context, project


@pytest_asyncio.fixture
async def memdb(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'hermetic.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(text)")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    now = dt.datetime.utcnow()
    async with m() as db:
        await db.execute(sa_text("INSERT INTO collections (id, name, created_at) VALUES (1, 'c', :ts)"), {"ts": now})
        await db.execute(sa_text(
            "INSERT INTO knowledge_chunks (spawn_id, collection_id, source, chunk_index, text, created_at) "
            "VALUES (NULL, 1, 'policy.txt', 0, 'Refund policy is 30 days for all orders.', :ts)"), {"ts": now})
        rid = (await db.execute(sa_text("SELECT id FROM knowledge_chunks WHERE source='policy.txt'"))).scalar_one()
        await db.execute(sa_text("INSERT INTO knowledge_chunks_fts (rowid, text) VALUES (:r, :t)"),
                         {"r": rid, "t": "Refund policy is 30 days for all orders."})
        db.add(project([1]))
        await db.commit()
    return m


async def test_hermetic_record_usage_false_writes_no_usage(memdb):
    from server.db.models import BrainUsage
    from server.services import knowledge

    with pc.bind(context()):
        hits = await knowledge.retrieve_scoped("refund", spawn_id=None, record_usage=False)
    assert hits, "the scope must find the chunk, or this test proves nothing"
    async with memdb() as s:
        assert (await s.execute(select(BrainUsage))).scalars().all() == []

    with pc.bind(context()):                     # the same retrieval, counted: it does record
        await knowledge.retrieve_scoped("refund", spawn_id=None, record_usage=True)
    async with memdb() as s:
        assert len((await s.execute(select(BrainUsage))).scalars().all()) == 1
