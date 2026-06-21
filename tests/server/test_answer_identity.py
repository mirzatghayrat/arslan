"""Regression: Arslan must not adopt a spawn's identity from contaminated history.

Root cause: assemble_working_context flattened spawn_summary (a spawn's relayed output,
often first-person) into a generic 'assistant' turn, so the answer model continued the
spawn's persona ("我是 Mermer" / "我是领英智囊"). Two-part fix:
  A) attribute spawn_summary turns as relayed spawn output (not Arslan's own voice);
  B) lock Arslan's identity in the system prompt so it never adopts a teammate's persona.
"""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.orchestrator import arslan


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'id.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_create)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def test_arslan_system_locks_identity():
    """Fix B: the answer system prompt asserts Arslan's identity and forbids adopting a
    teammate/spawn persona from earlier turns."""
    s = arslan._ARSLAN_SYSTEM.lower()
    assert "arslan" in s
    assert "spawn" in s or "teammate" in s
    assert ("never adopt" in s) or ("not any of your spawns" in s) or ("always speak as arslan" in s)


@pytest.mark.asyncio
async def test_spawn_output_attributed_in_history(maker):
    """Fix A: a spawn_summary turn is framed as relayed spawn output, not Arslan's own voice."""
    from server.orchestrator import memory

    await memory.add_message("c1", "user", "出来mermer")
    await memory.add_message("c1", "spawn_summary", "[Mermer] 你好，我是 Mermer 你的个人助理")
    ctx = await memory.assemble_working_context("c1")
    spawn_turn = ctx["history"][-1]
    assert spawn_turn["role"] == "assistant"
    # must carry a spawn-attribution marker so the model knows it was a teammate, not Arslan
    assert "spawn" in spawn_turn["content"].lower()
    assert spawn_turn["content"] != "[Mermer] 你好，我是 Mermer 你的个人助理"


@pytest.mark.asyncio
async def test_arslan_own_and_user_turns_unchanged(maker):
    """Arslan's own turns and user turns are passed through verbatim (only spawn turns reframed)."""
    from server.orchestrator import memory

    await memory.add_message("c2", "user", "hi")
    await memory.add_message("c2", "arslan", "Hi! I'm Arslan.")
    ctx = await memory.assemble_working_context("c2")
    assert ctx["history"][0] == {"role": "user", "content": "hi"}
    assert ctx["history"][1] == {"role": "assistant", "content": "Hi! I'm Arslan."}
