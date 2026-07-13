import pytest
import pytest_asyncio
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.services import knowledge, learning_service


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'learn.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(text)")
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(text)")

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


class _FakeAdapter:
    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        class R:
            content = "做 OKX deck 时优先套用暗色磨砂玻璃模板"
        return R()


@pytest.mark.asyncio
async def test_distill_writes_learning_with_source_ref(maker, monkeypatch):
    monkeypatch.setattr(learning_service, "_get_adapter", lambda: _FakeAdapter())
    n = await learning_service.distill_from_event(
        conversation_id="conv-a", spawn_id=3, spawn_name="Deck Master",
        signal_text="用户要 OKX 报告,Arslan 亲自做了一版暗色磨砂玻璃 deck")
    assert n == 1
    async with db_session.AsyncSessionLocal() as db:
        row = (await db.execute(sa_text(
            "SELECT content, source_kind, source_ref FROM learnings ORDER BY id DESC LIMIT 1"))).first()
    assert "OKX" in row[0]
    assert row[1] == "distill"
    assert row[2] is not None  # source_ref always present


@pytest.mark.asyncio
async def test_distill_fail_open_produces_nothing(maker, monkeypatch):
    class _Boom:
        async def chat(self, system, user, history=None, tools=None, temperature=0.7):
            raise RuntimeError("llm down")

    monkeypatch.setattr(learning_service, "_get_adapter", lambda: _Boom())
    n = await learning_service.distill_from_event(
        conversation_id="c", spawn_id=1, spawn_name="X", signal_text="anything")
    assert n == 0  # nothing produced beats producing a fake


@pytest.mark.asyncio
async def test_retrieve_folds_in_learnings(maker, monkeypatch):
    monkeypatch.setattr(learning_service, "_get_adapter", lambda: _FakeAdapter())
    await learning_service.distill_from_event(
        conversation_id="c", spawn_id=None, spawn_name=None, signal_text="做 deck 的心得")
    out = await knowledge.retrieve_scoped("OKX", spawn_id=None, k=5, used_ref="c")
    assert any(src.startswith("心得#") for src, _ in out)
