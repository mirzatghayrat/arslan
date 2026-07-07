import anyio
import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.orchestrator import memory
from server.services import fact_classify, fact_dedup


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'facts.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    # keep the write path hermetic — no background classify LLM call (and no
    # un-awaited coroutine: neutralize classify_ids before schedule sees it)
    monkeypatch.setattr(fact_classify, "classify_ids", lambda ids: None)
    monkeypatch.setattr(fact_classify, "schedule", lambda *a, **k: None)
    return m


def test_similar_catches_near_duplicates():
    assert fact_dedup.similar("用户需要广告科技助手", "用户需要广告科技（AdTech）行业相关的助手") is True
    assert fact_dedup.similar("用户在北京工作", "用户来自甲城,是甲语母语者") is False


@pytest.mark.asyncio
async def test_save_facts_merges_near_dup_and_bumps_confidence(maker):
    a = await memory.save_facts([{"content": "用户偏好使用中文沟通"}])
    assert len(a) == 1
    fid = a[0].id
    b = await memory.save_facts([{"content": "用户偏好使用中文进行沟通和输出"}])
    # merged into existing → no new row created
    assert b == []
    async with db_session.AsyncSessionLocal() as db:
        conf = (await db.execute(sa_text(
            "SELECT confidence FROM user_facts WHERE id = :i"), {"i": fid})).scalar_one()
    assert conf > 0.6  # bumped on re-observation


@pytest.mark.asyncio
async def test_dedup_merge_backfill_collapses(maker):
    await memory.save_facts([{"content": "用户是甲语母语者,来自甲城"}])
    # inject an exact near-dup directly (bypass save's own merge) to backfill
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(sa_text(
            "INSERT INTO user_facts (content, source, confidence) VALUES "
            "('用户是甲语母语者,来自甲城地区', 'auto', 0.6)"))
        await db.commit()
    deleted = await fact_dedup.dedup_merge_facts()
    assert deleted == 1
