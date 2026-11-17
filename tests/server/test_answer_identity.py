"""Regression: Arslan must not adopt a spawn's identity from contaminated history.

Root cause: assemble_working_context flattened spawn_summary (a spawn's relayed output,
often first-person) into a generic 'assistant' turn, so the answer model continued the
spawn's persona ("我是 Mermer" / "我是领英智囊"). Two-part fix:
  A) attribute spawn_summary turns as relayed spawn output (not Arslan's own voice); since C7c-5c the
     attribution is in the data (0103 prefixes those rows; tests/server/test_migration_0103.py);
  B) lock Arslan's identity in the system prompt so it never adopts a teammate's persona.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.orchestrator import arslan


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'id.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def test_arslan_system_is_one_agent_with_no_team():
    """0.1.48: one Arslan. The identity prompt names Arslan and never mentions a team,
    specialists or spawns (it used to describe coordinating 'a team of specialist spawns')."""
    s = arslan._ARSLAN_SYSTEM.lower()
    assert "arslan" in s and "user's language" in s
    stable = arslan._ANSWER_STABLE_PREFIX.lower()
    assert not any(word in stable for word in ("spawn", "specialist", "teammate", "your team", "分身"))


@pytest.mark.asyncio
async def test_arslan_own_and_user_turns_unchanged(maker):
    """Arslan's own turns and user turns are passed through verbatim (only spawn turns reframed)."""
    from server.orchestrator import memory

    await memory.add_message("c2", "user", "hi")
    await memory.add_message("c2", "arslan", "Hi! I'm Arslan.")
    ctx = await memory.assemble_working_context("c2")
    assert ctx["history"][0] == {"role": "user", "content": "hi"}
    assert ctx["history"][1] == {"role": "assistant", "content": "Hi! I'm Arslan."}
