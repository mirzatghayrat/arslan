"""Metaknowledge upflow: after per-spawn distillation, ONE cross-spawn meta-fact
bubbles up to Arslan's user profile (UserFact, source='upflow')."""
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn, UserFact


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'up.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with m() as s:
        s.add(Spawn(id=3, name="小美", domain_category="content",
                    system_prompt="sp", memory_facts=[]))
        await s.commit()

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def _stub_adapter(monkeypatch, reply: str):
    """Stub build_adapter the same way the real judgment path is stubbed."""
    from server.services import distill_service

    class _Resp:
        content = reply

    class _Adapter:
        async def chat(self, system, user):
            return _Resp()

    async def fake_build_adapter(*a, **k):
        return _Adapter()

    monkeypatch.setattr(distill_service, "build_adapter", fake_build_adapter)


async def test_upflow_writes_userfact(maker, monkeypatch):
    from server.services import distill_service
    _stub_adapter(monkeypatch, "用户偏口语、忌硬广")

    async with maker() as db:
        spawn = await db.get(Spawn, 3)
        written = await distill_service.distill_meta_upflow(
            db, spawn, ["输出更简短", "标注信息来源"])
        await db.commit()
    async with maker() as s:
        rows = (await s.execute(select(UserFact))).scalars().all()

    assert written == "用户偏口语、忌硬广"
    assert len(rows) == 1
    assert rows[0].content == "用户偏口语、忌硬广"
    assert rows[0].source == "upflow"


async def test_upflow_empty_reply_writes_nothing(maker, monkeypatch):
    from server.services import distill_service
    _stub_adapter(monkeypatch, "   ")  # LLM says nothing worth upflowing

    async with maker() as db:
        spawn = await db.get(Spawn, 3)
        written = await distill_service.distill_meta_upflow(db, spawn, ["细节偏好"])
        await db.commit()
    async with maker() as s:
        rows = (await s.execute(select(UserFact))).scalars().all()

    assert written is None
    assert rows == []


async def test_upflow_dedup_skips_existing(maker, monkeypatch):
    from server.services import distill_service
    _stub_adapter(monkeypatch, "用户偏口语")

    async with maker() as s:
        s.add(UserFact(content="用户偏口语、忌硬广", source="manual"))
        await s.commit()
    async with maker() as db:
        spawn = await db.get(Spawn, 3)
        written = await distill_service.distill_meta_upflow(db, spawn, ["偏好"])
        await db.commit()
    async with maker() as s:
        rows = (await s.execute(select(UserFact))).scalars().all()

    # "用户偏口语" is contained in the existing fact → dedup, not written again
    assert written is None
    assert len(rows) == 1


async def test_upflow_empty_new_facts_noop(maker, monkeypatch):
    from server.services import distill_service
    calls = {"n": 0}

    async def fake_build_adapter(*a, **k):
        calls["n"] += 1
        raise AssertionError("LLM must not be called for empty new_facts")

    monkeypatch.setattr(distill_service, "build_adapter", fake_build_adapter)

    async with maker() as db:
        spawn = await db.get(Spawn, 3)
        written = await distill_service.distill_meta_upflow(db, spawn, [])
        await db.commit()
    async with maker() as s:
        rows = (await s.execute(select(UserFact))).scalars().all()

    assert written is None
    assert rows == []
    assert calls["n"] == 0
