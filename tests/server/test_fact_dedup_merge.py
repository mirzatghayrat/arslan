import pytest
import pytest_asyncio
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.orchestrator import memory
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
    assert fact_dedup.similar("用户在北京工作", "用户来自甲城,是甲语母语者") is False


@pytest.mark.asyncio
async def test_save_facts_near_dup_coexists_not_merged(maker):
    # P0-b: this paraphrase pair has difflib ratio == 0.800 (verified via
    # difflib.SequenceMatcher; norm() is a no-op here — no whitespace/case to
    # collapse) and containment doesn't apply (neither string is a substring of
    # the other). Under the OLD threshold (0.6) it silently merged; under the
    # NEW threshold (0.85) it's not classified as similar at all, so it inserts
    # as an independent fact — no merge, no bump, both rows kept (coexist).
    # This guards against the tightened threshold's core risk: two distinct
    # paraphrases must never be silently conflated (see the 喜欢猫/喜欢狗
    # regression this round fixes). Only exact-normalized duplicates merge —
    # see test_dedup_tightened.py::test_exact_dup_merges_and_bumps.
    a = await memory.save_facts([{"content": "用户偏好使用中文沟通"}], provenance={"source_kind": "test"})
    assert len(a) == 1
    fid = a[0].id
    b = await memory.save_facts(
        [{"content": "用户偏好使用中文进行沟通和输出"}], provenance={"source_kind": "test"})
    assert len(b) == 1  # NOT merged → a new row is created (coexist)
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(sa_text(
            "SELECT id, content, confidence FROM user_facts ORDER BY id"))).all()
    assert len(rows) == 2
    conf = next(r[2] for r in rows if r[0] == fid)
    assert conf == 0.6  # original row NOT bumped — it wasn't touched


@pytest.mark.asyncio
async def test_dedup_merge_backfill_collapses(maker):
    await memory.save_facts(
        [{"content": "用户是甲语母语者,来自甲城"}], provenance={"source_kind": "test"})
    # inject an exact near-dup directly (bypass save's own merge) to backfill
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(sa_text(
            "INSERT INTO user_facts (content, source, confidence) VALUES "
            "('用户是甲语母语者,来自甲城地区', 'auto', 0.6)"))
        await db.commit()
    deleted = await fact_dedup.dedup_merge_facts()
    assert deleted == 1
