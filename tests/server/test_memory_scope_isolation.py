"""RememberExecutor's identity refusals, which run before any write: a missing caller, a spawn actor without
a real spawn_id, and an unknown actor string are all refused (fail-closed, never guessed). A spawn deleting an
orphan learning with no owner is refused too.

0.1.63 C2a-2 removed this file's v1 cases (direct own-well writes, Tier2 MemoryProposal downgrades, cross-well
checks on v1 tables): the v1 write path is gone. Memory v2's write rules are tested in
tests/server/test_memory_tools_v2.py (worker confirmations, destructive actions, the cloud gate). Where an
expert's own write lands (its expert scope) has no dedicated test: experts are off and C7 removes them.
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Learning, MemoryProposal, Spawn, UserFact
from server.orchestrator.tool_caller import ToolCaller, reset_caller, set_caller
from server.registry.memory_executors import RememberExecutor


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'scope.db'}")
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


async def _seed_spawn(maker, spawn_id: int, name: str, memory_facts: list | None = None) -> None:
    async with maker() as db:
        db.add(Spawn(id=spawn_id, name=name, domain_category="d", system_prompt="p",
                     memory_facts=memory_facts or []))
        await db.commit()


async def _remember(args: dict, caller: ToolCaller) -> dict:
    token = set_caller(caller)
    try:
        return await RememberExecutor().execute(args)
    finally:
        reset_caller(token)


# ---------------------------------------------------------------------------
# fail-closed identity
# ---------------------------------------------------------------------------

async def test_caller_none_refuses_write(maker):
    from server.orchestrator import tool_caller
    assert tool_caller.current_caller() is None
    out = await RememberExecutor().execute({"kind": "fact", "action": "append", "content": "x"})
    assert out == {"ok": False, "error": "no caller context; refusing to write"}


async def test_spawn_actor_without_real_spawn_id_is_refused(maker):
    out = await _remember(
        {"kind": "learning", "action": "append", "content": "x"},
        ToolCaller(actor="spawn", spawn_id=None, conversation_id="c1"))
    assert out["ok"] is False
    assert "spawn_id" in out["error"]


async def test_unknown_actor_is_refused_not_treated_as_host(maker):
    """Fail-closed on identity (whole-branch review): the routing treats
    'not spawn' as host, so a garbage actor string must be refused explicitly
    rather than inherit host privileges (direct global writes)."""
    out = await _remember(
        {"kind": "fact", "action": "append", "content": "别把我当 host"},
        ToolCaller(actor="root", spawn_id=None, conversation_id="c1"))
    assert out["ok"] is False
    assert "unknown caller actor" in out["error"]
    # and nothing was written
    async with maker() as db:
        facts = (await db.execute(select(UserFact))).scalars().all()
    assert facts == []


# ---------------------------------------------------------------------------
# spawn writes its own well directly (Tier1, no scope violation)
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# spawn writing a GLOBAL table (fact/note) always downgrades to a Tier2 proposal
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# host writing a spawn's preference always proposes (needs an explicit target)
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# preference delete — ownership guard (Task 5 self-check, Minor #3): a spawn
# may only ever propose deleting its OWN preferences; host always needs an
# explicit target (mirrors the append/overwrite case above). Task 5's accept
# endpoint reads provenance["target_spawn_id"] to materialize the delete, so
# it must always be present and correct on the proposal row.
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# cross-well supersede rejection
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Fix 2 (whole-branch review, cross-well ownership symmetry): a spawn
# proposing to delete a learning must be scoped to its OWN well, exactly
# like supersede above and preference-delete's ownership guard -- otherwise
# the human accepting the proposal is blind to it being another spawn's
# memory. Note-delete has no per-spawn ownership concept (notes are global)
# so it stays an unrestricted Tier2 proposal, but the reason is annotated
# so the cross-scope nature is visible to the human. Host is unrestricted.
# ---------------------------------------------------------------------------



async def test_spawn_delete_orphan_learning_with_no_spawn_id_is_refused(maker):
    """spawn_id is nullable on Learning -- an orphaned/legacy row with no
    owner at all is exactly as out-of-scope for a spawn as another spawn's
    row (never silently treated as "fair game" just because it's unowned)."""
    await _seed_spawn(maker, 28, "分身28")
    async with maker() as db:
        orphan = Learning(content="没有主人的心得", source_kind="distill",
                          source_ref={}, spawn_id=None)
        db.add(orphan)
        await db.commit()
        orphan_id = orphan.id

    out = await _remember(
        {"kind": "learning", "action": "delete", "target_id": orphan_id},
        ToolCaller(actor="spawn", spawn_id=28, conversation_id="c1"))
    assert out["ok"] is False

    async with maker() as db:
        proposals = (await db.execute(select(MemoryProposal))).scalars().all()
    assert proposals == []

