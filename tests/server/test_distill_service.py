import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn, ArslanMessage, DistilledSession


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'ds.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with m() as s:
            s.add(Spawn(id=3, name="小美", domain_category="content", system_prompt="sp", memory_facts=[]))
            s.add(ArslanMessage(conversation_id="c1", role="user", content="把报告写短点"))
            s.add(ArslanMessage(conversation_id="c1", role="spawn_summary", content="短报告", display_content="短报告", spawn_id=3))
            await s.commit()
    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def test_distill_writes_facts_and_marks(maker, monkeypatch):
    from server.services import distill_service
    async def fake_distill_facts(existing, signals):
        return ["用户偏好更简短的输出"]
    monkeypatch.setattr(distill_service, "distill_facts", fake_distill_facts)
    async def _run():
        await distill_service.distill_session("c1")
        async with maker() as s:
            spawn = await s.get(Spawn, 3)
            marks = (await s.execute(select(DistilledSession).where(
                DistilledSession.conversation_id == "c1", DistilledSession.spawn_id == 3))).scalars().all()
        return spawn.memory_facts, marks
    facts, marks = anyio.run(_run)
    assert facts == ["用户偏好更简短的输出"] and len(marks) == 1


def test_distill_idempotent(maker, monkeypatch):
    from server.services import distill_service
    calls = {"n": 0}
    async def fake_distill_facts(existing, signals):
        calls["n"] += 1
        return ["x"]
    monkeypatch.setattr(distill_service, "distill_facts", fake_distill_facts)
    async def _run():
        await distill_service.distill_session("c1")
        await distill_service.distill_session("c1")   # second pass: already marked
        return calls["n"]
    assert anyio.run(_run) == 1   # distilled once


def test_distill_llm_failure_keeps_existing(maker, monkeypatch):
    from server.services import distill_service
    async def boom(existing, signals):
        raise RuntimeError("llm down")
    monkeypatch.setattr(distill_service, "distill_facts", boom)
    async def _run():
        await distill_service.distill_session("c1")   # must not raise
        async with maker() as s:
            return (await s.get(Spawn, 3)).memory_facts
    assert anyio.run(_run) == []   # unchanged
