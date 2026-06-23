import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import ArslanMessage, Base, ChatMessage, Spawn
from server.orchestrator import dispatcher


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
        for piece in ["hello ", "world"]:
            yield piece


async def test_persist_false_writes_nothing_and_uses_override(memdb, monkeypatch):
    async with memdb() as db:
        spawn = Spawn(name="S", domain_category="x", system_prompt="ORIGINAL PROMPT")
        db.add(spawn)
        await db.commit()
        await db.refresh(spawn)
        spawn_id = spawn.id

    sink = {}
    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _FakeAdapter(sink))

    out = await dispatcher.dispatch(
        "conv-eval", spawn_id=spawn_id, task_brief="do X",
        system_prompt_override="CANDIDATE PROMPT", persist=False,
    )

    assert out["full_output"] == "hello world"
    assert out["summary_message_id"] is None
    assert out["assistant_message_id"] is None
    assert sink["system"].startswith("CANDIDATE PROMPT")

    async with memdb() as db:
        cm = (await db.execute(select(func.count()).select_from(ChatMessage))).scalar_one()
        am = (await db.execute(select(func.count()).select_from(ArslanMessage))).scalar_one()
    assert cm == 0 and am == 0


async def test_persist_true_still_writes(memdb, monkeypatch):
    async with memdb() as db:
        spawn = Spawn(name="S2", domain_category="x", system_prompt="ORIGINAL")
        db.add(spawn)
        await db.commit()
        await db.refresh(spawn)
        spawn_id = spawn.id

    sink = {}
    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _FakeAdapter(sink))
    out = await dispatcher.dispatch("conv", spawn_id=spawn_id, task_brief="do X")
    assert out["summary_message_id"] is not None
    assert sink["system"].startswith("ORIGINAL")   # no override → original base prompt
    async with memdb() as db:
        cm = (await db.execute(select(func.count()).select_from(ChatMessage))).scalar_one()
        am = (await db.execute(select(func.count()).select_from(ArslanMessage))).scalar_one()
    assert cm == 2
    assert am == 1   # spawn_summary persisted
