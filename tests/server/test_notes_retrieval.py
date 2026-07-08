import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'notes_retr.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.exec_driver_sql(
                "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(text)")
            await conn.exec_driver_sql(
                "CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(text)")
            await conn.exec_driver_sql(
                "CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text)")

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_notes_are_retrievable(maker):
    from server.services import note_service, knowledge, brain_usage
    await note_service.create("报销规则", "报销 上限 500 元,超过要审批", ["finance"])
    out = await knowledge.retrieve_scoped("报销", spawn_id=None, k=5, used_ref="c")
    assert any(src.startswith("笔记:") for src, _ in out)
    mp = await brain_usage.usage_map([("note", "note:1")])
    assert mp.get(("note", "note:1"), {}).get("usage_count", 0) >= 1
