"""brain-P2 Task 6: dual-track provenance — agentic vs Tier0/distill writes, in the
SAME table, are distinguishable by querying. One agentic row AND one live Tier0 row
go into the learnings table via each path's real production write, then both are
read back and their provenance must actually differ, not just equal a literal.

C2a removed the weak-model acceptance test and the fact half of the dual-track test:
both asserted v1 user_facts rows written through memory.save_facts. On memory v2 a
fact forming after an answer with no tool call is checked by
tests/server/test_arslan_loop.py::test_answer_path_streams_and_persists. The
learnings half tests v1 code that C2a-2 deletes.
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Learning, Spawn
from server.orchestrator.tool_caller import ToolCaller, reset_caller, set_caller
from server.registry.memory_executors import RememberExecutor


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'dual.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text)")
        await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(text)")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest_asyncio.fixture(autouse=True)
async def _no_caller_leak():
    from server.orchestrator import tool_caller
    assert tool_caller.current_caller() is None
    yield
    assert tool_caller.current_caller() is None


async def _remember(args: dict, caller: ToolCaller) -> dict:
    token = set_caller(caller)
    try:
        return await RememberExecutor().execute(args)
    finally:
        reset_caller(token)


async def _seed_spawn(maker, spawn_id: int, name: str) -> None:
    async with maker() as db:
        db.add(Spawn(id=spawn_id, name=name, domain_category="d", system_prompt="p",
                     memory_facts=[]))
        await db.commit()


# ---------------------------------------------------------------------------
# dual-track provenance: agentic and Tier0/distill writes in the SAME table are
# distinguishable by querying (the learning's source_ref.actor).
# ---------------------------------------------------------------------------

async def test_dual_track_learning_provenance_distinguishable(maker, monkeypatch):
    """learnings: one agentic write (RememberExecutor, source_ref.actor) and one
    Tier0 write (learning_service.distill_from_event, source_kind='distill' —
    the real session-distill call-site) land in the SAME table (same well,
    spawn_id=61). Querying each back proves the two tracks are distinguishable
    via source_kind/source_ref alone."""
    await _seed_spawn(maker, 61, "分身61")

    agentic_out = await _remember(
        {"kind": "learning", "action": "append", "content": "轨道一:agentic spawn 心得"},
        ToolCaller(actor="spawn", spawn_id=61, conversation_id="c-agentic"))
    assert agentic_out["ok"] is True

    from server.services import learning_service

    class _Resp:
        content = "轨道二:Tier0 distill 心得"

    class _StubAdapter:
        async def chat(self, system, user, **kw):
            return _Resp()

    async def _fake_build_adapter(*a, **kw):
        return _StubAdapter()

    monkeypatch.setattr(learning_service, "build_adapter", _fake_build_adapter)
    tier0_id = await learning_service.distill_from_event(
        conversation_id="c-tier0", spawn_id=61, spawn_name="分身61",
        signal_text="真实会话信号")
    assert tier0_id > 0

    async with maker() as db:
        agentic_row = await db.get(Learning, agentic_out["id"])
        tier0_row = await db.get(Learning, tier0_id)

    assert agentic_row.source_kind == "agentic"
    assert agentic_row.source_ref["actor"] == "spawn:61"
    assert tier0_row.source_kind == "distill"
    assert "actor" not in tier0_row.source_ref                  # distill never sets "actor"
    assert agentic_row.source_kind != tier0_row.source_kind     # distinguishable, queried live
