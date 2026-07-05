import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, Spawn
from server.orchestrator import dispatcher
from server.services import knowledge


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


class _FakeAdapter:
    def __init__(self, sink):
        self._sink = sink

    async def chat_stream(self, system, user, history=None):
        self._sink["system"] = system
        yield "ok"


async def _spawn(Session) -> int:
    async with Session() as db:
        s = Spawn(name="S", domain_category="x", system_prompt="BASE")
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


async def test_dispatch_injects_retrieved_knowledge(memdb, monkeypatch):
    sid = await _spawn(memdb)
    sink = {}
    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _FakeAdapter(sink))

    async def fake_retrieve(query, *, spawn_id, k=5):
        return [("policy.txt", "Refund policy: 30 days.")]
    monkeypatch.setattr(knowledge, "retrieve_scoped", fake_retrieve)

    await dispatcher.dispatch("c", spawn_id=sid, task_brief="refund?", persist=False)
    assert "Refund policy: 30 days." in sink["system"]


async def test_dispatch_injects_attached_context(memdb, monkeypatch):
    sid = await _spawn(memdb)
    sink = {}
    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _FakeAdapter(sink))

    await dispatcher.dispatch(
        "c", spawn_id=sid, task_brief="summarize", persist=False, attached_context="DOCX BODY HERE"
    )
    assert "DOCX BODY HERE" in sink["system"]


async def test_dispatch_survives_retrieval_error(memdb, monkeypatch):
    sid = await _spawn(memdb)
    sink = {}
    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _FakeAdapter(sink))

    async def boom(query, *, spawn_id, k=5):
        raise RuntimeError("fts down")
    monkeypatch.setattr(knowledge, "retrieve_scoped", boom)

    out = await dispatcher.dispatch("c", spawn_id=sid, task_brief="x", persist=False)
    assert out["full_output"] == "ok"
