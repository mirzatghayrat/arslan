import logging

import pytest

from server.db import session as db_session
from server.services.fact_dedup import similar


def test_different_short_cjk_facts_not_similar():
    assert similar("喜欢猫", "喜欢狗") is False        # 旧 0.6 这里是 True——核心回归


def test_exact_still_similar():
    assert similar("abc", "abc") is True


def test_real_containment_still_similar():
    # 两串均 >= 8:真前缀扩展仍判重(containment 分支)
    assert similar("我住在北京市朝阳区", "我住在北京市朝阳区望京") is True


def test_short_containment_disabled():
    assert similar("猫", "猫粮") is False              # 短串禁 containment


@pytest.fixture
async def maker(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from server.db.models import Base
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'d.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # learning_service._write inserts into this FTS5 shadow table; it isn't
        # part of Base.metadata (created via migration in prod), so tests that
        # exercise _write must create it here (mirrors test_learning_service.py).
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(text)")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    yield m
    await engine.dispose()


async def _contents(maker):
    from sqlalchemy import select
    from server.db.models import UserFact
    async with maker() as db:
        rows = (await db.execute(select(UserFact).order_by(UserFact.id))).scalars().all()
        return [(r.content, r.confidence) for r in rows]


async def test_exact_dup_merges_and_bumps(maker):
    from server.orchestrator.memory import save_facts
    await save_facts([{"content": "喜欢猫"}])
    await save_facts([{"content": "喜欢猫"}])
    rows = await _contents(maker)
    assert len(rows) == 1 and rows[0][1] > 0.6            # 一行,confidence 升


async def test_fuzzy_coexists_not_dropped(maker, caplog):
    from server.orchestrator.memory import save_facts
    await save_facts([{"content": "喜欢猫"}])
    with caplog.at_level(logging.INFO):
        await save_facts([{"content": "喜欢狗"}])          # 0.667 < 0.85:非近重,直接存
        await save_facts([{"content": "喜欢猫咪们呀"}])    # 若模糊命中则并存+留痕
    rows = await _contents(maker)
    contents = [c for c, _ in rows]
    assert "喜欢猫" in contents and "喜欢狗" in contents   # 不再丢弃


async def test_two_phase_exact_wins_over_fuzzy_sibling(maker):
    # I1 锚定:模糊兄弟排在精确重复之前,不许误插
    from server.orchestrator.memory import save_facts
    await save_facts([{"content": "我喜欢猫咪"}])          # id1(与目标 ratio 0.889 模糊)
    await save_facts([{"content": "我喜欢猫"}])            # id2(精确目标;与 id1 模糊并存)
    n_before = len(await _contents(maker))
    await save_facts([{"content": "我喜欢猫"}])            # 再写:必须与 id2 精确合并
    rows = await _contents(maker)
    assert len(rows) == n_before                           # 不新增行
    assert any(c == "我喜欢猫" and conf > 0.6 for c, conf in rows)  # id2 被 bump


async def test_learning_fuzzy_coexists_exact_skips(maker):
    from server.services.learning_service import _write
    assert await _write("总结要先给结论", "l1", "session", {}, None) == 1
    assert await _write("总结要先给结论", "l1", "session", {}, None) == 0   # 精确跳过
    assert await _write("总结时应当先给出结论呀", "l2", "session", {}, None) == 1  # 模糊并存
