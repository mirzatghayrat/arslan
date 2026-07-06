"""LLM fact classification into a FIXED enum; fail-open to 其他; single-flight backfill."""
import anyio
import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, UserFact


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'c.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
        async with m() as s:
            s.add(UserFact(id=1, content="用户在北京工作", source="auto"))
            s.add(UserFact(id=2, content="用户喜欢中文沟通", source="auto"))
            await s.commit()
    anyio.run(_seed)
    return m


class _Adapter:
    def __init__(self, reply):
        self.reply = reply

    async def chat(self, system, user, **kw):
        class _R:
            content = None
        _R.content = self.reply
        return _R


def test_classify_one_returns_only_enum(maker, monkeypatch):
    from server.services import fact_classify
    async def _fake(role=None): return _Adapter("身份背景")
    monkeypatch.setattr(fact_classify, "build_adapter", _fake)
    assert anyio.run(lambda: fact_classify.classify_one("用户在北京工作")) == "身份背景"


def test_classify_one_illegal_reply_falls_open_to_other(maker, monkeypatch):
    from server.services import fact_classify
    async def _fake(role=None): return _Adapter("这不是合法类别哈哈")
    monkeypatch.setattr(fact_classify, "build_adapter", _fake)
    assert anyio.run(lambda: fact_classify.classify_one("x")) == "其他"


def test_classify_missing_only_touches_null(maker, monkeypatch):
    from server.services import fact_classify
    async def _fake(role=None): return _Adapter("沟通偏好")
    monkeypatch.setattr(fact_classify, "build_adapter", _fake)
    async def _pre():
        async with maker() as s:
            await s.execute(sa_text("UPDATE user_facts SET category='身份背景' WHERE id=1"))
            await s.commit()
    anyio.run(_pre)
    done = anyio.run(lambda: fact_classify.classify_missing())
    assert done == 1
    async def _check():
        async with maker() as s:
            return (await s.execute(sa_text("SELECT category FROM user_facts ORDER BY id"))).scalars().all()
    assert anyio.run(_check) == ["身份背景", "沟通偏好"]
