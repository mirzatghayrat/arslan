"""Exact-normalized fact dedup: the backfill keeps the earliest of each group.

The write-time tests (memory.py's v1 dedup and its fail-open) went with that path in C2a: memory v2
skips near-duplicates in memory_compat.save_facts. The backfill is v1 code that C2a-2 deletes."""
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'d.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def test_norm_collapses_whitespace_and_ascii_case():
    from server.services.fact_dedup import norm
    assert norm("  Hello   World ") == norm("hello world")
    assert norm("用户 想建 分身") == "用户 想建 分身"



