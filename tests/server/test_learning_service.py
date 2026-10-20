import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.services import knowledge, learning_service


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'learn.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(text)")
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(text)")

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_public_append_returns_real_row_id(maker):
    """brain-P2 Task 4 BLOCKER fix: the public, id-returning entry point (a thin
    wrapper over `_write`) RememberExecutor's supersede path depends on."""
    from sqlalchemy import select

    from server.db.models import Learning

    n = await learning_service.append(
        "先读文档再动手", label="l1", source_kind="agentic",
        source_ref={"actor": "host", "conversation_id": "c1"}, spawn_id=None)
    assert n > 0
    async with db_session.AsyncSessionLocal() as db:
        row = (await db.execute(
            select(Learning).where(Learning.id == n))).scalar_one()
    assert row.content == "先读文档再动手"
    assert row.source_ref["actor"] == "host"

    # exact-duplicate content is still skipped (dedup semantics preserved) -> 0
    dup = await learning_service.append(
        "先读文档再动手", label="l1", source_kind="agentic",
        source_ref={"actor": "host", "conversation_id": "c1"}, spawn_id=None)
    assert dup == 0


@pytest.mark.asyncio
async def test_retrieve_folds_in_learnings(maker):
    # 0.1.63 (C1c-1): written through append; the LLM distill that wrote it before is gone.
    await learning_service.append(
        "做 OKX deck 时优先套用暗色磨砂玻璃模板", label="心得", source_kind="distill",
        source_ref={"conversation_id": "c", "spawn_id": None}, spawn_id=None)
    out = await knowledge.retrieve_scoped("OKX", spawn_id=None, k=5, used_ref="c")
    assert any(src.startswith("心得#") for src, _ in out)
