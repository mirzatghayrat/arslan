"""Metaknowledge upflow: after per-spawn distillation, ONE cross-spawn meta-fact
bubbles up to Arslan's user profile. The test of the v1 UserFact it wrote went with
memory.save_facts' v1 path (C2a); the rest test v1 distill code that C2a-2 deletes."""
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


async def test_upflow_empty_reply_writes_nothing(maker, monkeypatch):
    from server.services import distill_service
    _stub_adapter(monkeypatch, "   ")  # LLM says nothing worth upflowing

    async with maker() as db:
        spawn = await db.get(Spawn, 3)
    written = await distill_service.distill_meta_upflow(spawn, ["细节偏好"])
    async with maker() as s:
        rows = (await s.execute(select(UserFact))).scalars().all()

    assert written is None
    assert rows == []


async def test_upflow_exact_dup_of_existing_merges_not_written_again(maker, monkeypatch):
    """brain-P1 Task 3: distill_meta_upflow's own ad-hoc containment dedup (which
    scanned ALL rows, including superseded ones — the BLOCKER #2 bug) is gone;
    dedup is now save_facts's disciplined two-phase (exact-norm merge / fuzzy
    coexist), active-only. An EXACT (norm) match merge-bumps rather than
    inserting a duplicate row."""
    from server.services import distill_service
    _stub_adapter(monkeypatch, "用户偏口语、忌硬广")

    async with maker() as s:
        s.add(UserFact(content="用户偏口语、忌硬广", source="manual"))
        await s.commit()
    async with maker() as db:
        spawn = await db.get(Spawn, 3)
    written = await distill_service.distill_meta_upflow(spawn, ["偏好"])
    async with maker() as s:
        rows = (await s.execute(select(UserFact))).scalars().all()

    assert written is None  # merge-bumped, not appended as a new row
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
    written = await distill_service.distill_meta_upflow(spawn, [])
    async with maker() as s:
        rows = (await s.execute(select(UserFact))).scalars().all()

    assert written is None
    assert rows == []
    assert calls["n"] == 0
