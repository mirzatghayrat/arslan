import pytest
import pytest_asyncio
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.services import fact_classify, fact_dedup


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'facts.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    # keep the write path hermetic — no background classify LLM call (and no
    # un-awaited coroutine: neutralize classify_ids before schedule sees it)
    monkeypatch.setattr(fact_classify, "classify_ids", lambda ids: None)
    monkeypatch.setattr(fact_classify, "schedule", lambda *a, **k: None)
    return m


def test_similar_catches_near_duplicates():
    # P0-b: threshold tightened 0.6 → 0.85. The old 广告科技 pair (difflib=0.606,
    # no containment — longer side is 23 chars, shorter 10, but they aren't a
    # prefix/suffix of one another) is BELOW the new threshold: no longer a
    # false-positive collision (this is the documented, intentional reversal —
    # see P0-b commit message).
    assert fact_dedup.similar("用户需要广告科技助手", "用户需要广告科技（AdTech）行业相关的助手") is False
    assert fact_dedup.similar("用户在乙城工作", "用户来自甲城,母语是甲语") is False


@pytest.mark.asyncio
async def test_dedup_merge_backfill_collapses(maker):
    # two near-dups written directly (memory.save_facts no longer writes v1 rows, C2a)
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(sa_text(
            "INSERT INTO user_facts (content, source, confidence) VALUES "
            "('用户母语是甲语,来自甲城', 'auto', 0.6), ('用户母语是甲语,来自甲城地区', 'auto', 0.6)"))
        await db.commit()
    deleted = await fact_dedup.dedup_merge_facts()
    assert deleted == 1
