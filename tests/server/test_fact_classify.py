"""LLM fact classification: few-shot, one call returns (category, label); fail-open."""
import pytest_asyncio
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, UserFact


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'c.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    async with m() as s:
        s.add(UserFact(id=1, content="用户在北京工作", source="auto", category="其他"))
        s.add(UserFact(id=2, content="用户喜欢中文沟通", source="auto"))
        await s.commit()
    return m


class _Adapter:
    def __init__(self, reply): self.reply = reply
    async def chat(self, system, user, **kw):
        class _R:
            content = None
        _R.content = self.reply
        return _R


def test_parse_json_category_and_label():
    from server.services.fact_classify import _parse
    assert _parse('{"category": "身份背景", "label": "北京工作"}') == ("身份背景", "北京工作")


def test_parse_illegal_category_falls_open():
    from server.services.fact_classify import _parse
    assert _parse('{"category": "不合法", "label": ""}') == ("其他", None)


def test_parse_non_json_substring_fallback():
    from server.services.fact_classify import _parse
    assert _parse("这条属于 沟通偏好 类") == ("沟通偏好", None)
    assert _parse("完全无关的回复") == ("其他", None)


async def test_classify_one_returns_tuple(maker, monkeypatch):
    from server.services import fact_classify
    async def _fake(role=None): return _Adapter('{"category":"身份背景","label":"北京工作"}')
    monkeypatch.setattr(fact_classify, "build_adapter", _fake)
    assert await fact_classify.classify_one("用户在北京工作") == ("身份背景", "北京工作")


async def test_classify_one_adapter_exception_fails_open(maker, monkeypatch):
    from server.services import fact_classify
    class _Boom:
        async def chat(self, system, user, **kw): raise RuntimeError("no key")
    async def _fake(role=None): return _Boom()
    monkeypatch.setattr(fact_classify, "build_adapter", _fake)
    assert await fact_classify.classify_one("x") == ("其他", None)


async def test_classify_missing_backfills_label_and_overwrites_category(maker, monkeypatch):
    from server.services import fact_classify
    async def _fake(role=None): return _Adapter('{"category":"沟通偏好","label":"中文沟通"}')
    monkeypatch.setattr(fact_classify, "build_adapter", _fake)
    done = await fact_classify.classify_missing()
    assert done == 2
    async with maker() as s:
        rows = (await s.execute(sa_text(
            "SELECT category, label FROM user_facts ORDER BY id"))).all()
    assert rows == [("沟通偏好", "中文沟通"), ("沟通偏好", "中文沟通")]


async def test_classify_missing_zero_pending_no_provider(maker, monkeypatch):
    from server.services import fact_classify
    def _boom(role=None): raise AssertionError("must not build adapter when 0 pending")
    monkeypatch.setattr(fact_classify, "build_adapter", _boom)
    async with maker() as s:
        await s.execute(sa_text("UPDATE user_facts SET label='x'"))
        await s.commit()
    assert await fact_classify.classify_missing() == 0
    assert fact_classify.classify_status()["error"] is None


async def test_classify_missing_surfaces_provider_failure_not_mislabel(maker, monkeypatch):
    from server.services import fact_classify
    class _Broken:
        async def chat(self, system, user, **kw): raise RuntimeError("db lookup exploded")
    async def _fake(role=None): return _Broken()
    monkeypatch.setattr(fact_classify, "build_adapter", _fake)
    done = await fact_classify.classify_missing()
    assert done == 0
    assert fact_classify.classify_status()["error"]
    async with maker() as s:
        rows = (await s.execute(sa_text("SELECT label FROM user_facts"))).scalars().all()
    assert rows == [None, None]


async def test_classify_ids_skips_on_outage_no_mislabel(maker, monkeypatch):
    """Write-time honest-fail path: if the provider is down while classifying a
    freshly-written fact, classify_ids must leave the row category/label NULL (for
    boot backfill) rather than persisting a mislabel — and must never raise."""
    from server.services import fact_classify
    class _Boom:
        async def chat(self, system, user, **kw): raise RuntimeError("provider down")
    async def _fake(role=None): return _Boom()
    monkeypatch.setattr(fact_classify, "build_adapter", _fake)
    # id=2 starts category=NULL, label=NULL. A failed classify must not touch it.
    await fact_classify.classify_ids([2])  # must not raise
    async with maker() as s:
        row = (await s.execute(sa_text(
            "SELECT category, label FROM user_facts WHERE id = 2"))).first()
    assert row == (None, None)  # left NULL, nothing mislabeled
