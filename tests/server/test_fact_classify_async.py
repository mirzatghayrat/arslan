"""Writes never block on classify; a fire-and-forget classify is scheduled."""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'a.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    anyio.run(_seed)
    return m


def _capture(monkeypatch):
    """Replace fact_classify.schedule with a recorder that closes the coro (so the
    real classify_ids never runs) and returns the captured-id list."""
    from server.services import fact_classify
    ids = []

    def _rec(coro):
        # coroutine is classify_ids([...]); pull the id list out of cr_frame locals,
        # then close it so it never executes against the DB in-test.
        try:
            captured = coro.cr_frame.f_locals.get("ids")
            if captured is not None:
                ids.append(list(captured))
        finally:
            coro.close()

    monkeypatch.setattr(fact_classify, "schedule", _rec)
    return ids


def test_add_manual_fact_schedules_classify_without_blocking(maker, monkeypatch):
    from server.orchestrator import memory
    from server.services import fact_classify
    scheduled = []
    monkeypatch.setattr(fact_classify, "schedule", lambda coro: (scheduled.append(1), coro.close()))
    row = anyio.run(lambda: memory.add_manual_fact("用户在上海工作"))
    assert row.id is not None            # write completed (returns the row)
    assert scheduled == [1]              # classify was scheduled (not awaited inline)


def test_save_facts_schedules_classify_for_created_ids(maker, monkeypatch):
    """save_facts commits the batch, then fire-and-forget schedules classify for the
    new rows' ids — write is durable, classify is not awaited inline."""
    from server.orchestrator import memory
    captured = _capture(monkeypatch)
    created = anyio.run(lambda: memory.save_facts([
        {"content": "用户在广州工作"}, {"content": "用户喜欢简短回答"},
    ]))
    assert [r.id for r in created] == [1, 2]      # both written + committed (ids assigned)
    assert captured == [[1, 2]]                    # scheduled once, for exactly the created ids


def test_distill_meta_upflow_schedules_after_flush(maker, monkeypatch):
    """distill_meta_upflow flushes the new UserFact (id assigned, caller commits) and
    schedules classify for that id — without awaiting it."""
    from server.services import distill_service

    class _Spawn:
        id = 7
        name = "研究员"
        domain_category = "research"

    class _Adapter:
        async def chat(self, system, user, **kw):
            class _R:
                content = "用户偏好数据驱动决策"
            return _R

    async def _fake(role=None):
        return _Adapter()

    monkeypatch.setattr(distill_service, "build_adapter", _fake)
    captured = _capture(monkeypatch)

    async def _run():
        async with db_session.AsyncSessionLocal() as db:
            fact = await distill_service.distill_meta_upflow(db, _Spawn(), ["数据驱动"])
            await db.commit()  # caller owns the commit
            return fact
    fact = anyio.run(_run)
    assert fact == "用户偏好数据驱动决策"
    assert captured == [[1]]  # the flushed row's id was scheduled for classify
