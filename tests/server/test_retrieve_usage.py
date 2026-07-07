import datetime as dt

import anyio
import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.services import brain_usage, knowledge


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'retr.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.exec_driver_sql(
                "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(text)")

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_retrieve_records_material_usage(maker):
    now = dt.datetime.utcnow()
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(sa_text("INSERT INTO collections (id, name, created_at) VALUES (1, 'c', :ts)"),
                         {"ts": now})
        await db.execute(sa_text(
            "INSERT INTO knowledge_chunks (spawn_id, collection_id, source, chunk_index, text, created_at) "
            "VALUES (NULL, 1, 'okx.pdf', 0, 'OKX 永续合约 保证金 杠杆', :ts)"), {"ts": now})
        rid = (await db.execute(sa_text("SELECT id FROM knowledge_chunks WHERE source='okx.pdf'"))).scalar_one()
        await db.execute(sa_text("INSERT INTO knowledge_chunks_fts (rowid, text) VALUES (:r, :t)"),
                         {"r": rid, "t": "OKX 永续合约 保证金 杠杆"})
        await db.commit()

    out = await knowledge.retrieve_scoped("OKX", spawn_id=None, k=5, used_ref="conv-x")
    assert any("OKX" in txt for _, txt in out)
    mp = await brain_usage.usage_map([("material", "material:coll:1:okx.pdf")])
    row = mp[("material", "material:coll:1:okx.pdf")]
    assert row["usage_count"] >= 1
    assert row["last_used_ref"] == "conv-x"
