"""Exact-normalized fact dedup: backfill keeps earliest; write-time skips dups."""
import anyio
import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, UserFact


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'d.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    anyio.run(_seed)
    return m


def test_norm_collapses_whitespace_and_ascii_case():
    from server.services.fact_dedup import norm
    assert norm("  Hello   World ") == norm("hello world")
    assert norm("用户 想建 分身") == "用户 想建 分身"


def test_dedup_keeps_earliest_of_each_group(maker):
    from server.services import fact_dedup
    async def _run():
        async with maker() as s:
            for c in ["建 GitHub 分身", "建 GitHub 分身", "  建 GitHub 分身 ", "别的偏好"]:
                s.add(UserFact(content=c, source="auto"))
            await s.commit()
        return await fact_dedup.dedup_facts()
    deleted = anyio.run(_run)
    assert deleted == 2
    async def _left():
        async with maker() as s:
            rows = (await s.execute(sa_text("SELECT id, content FROM user_facts ORDER BY id"))).all()
            return rows
    left = anyio.run(_left)
    assert [r[0] for r in left] == [1, 4]


def test_write_time_skip_existing(maker):
    from server.orchestrator import memory
    anyio.run(lambda: memory.add_manual_fact("建 GitHub 分身"))
    anyio.run(lambda: memory.add_manual_fact("  建 GitHub 分身  "))  # normalized dup → skipped
    async def _count():
        async with maker() as s:
            return (await s.execute(sa_text("SELECT COUNT(*) FROM user_facts"))).scalar_one()
    assert anyio.run(_count) == 1
