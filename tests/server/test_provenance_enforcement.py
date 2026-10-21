"""Provenance is mandatory on every fact write (brain-P1 Task 3). This is a programmer
guard — raise on empty/missing provenance — that fires before anything is written.

C2a removed the tests of the v1 rows' provenance, valid_from, confidence and
edited_by_user_at (after-answer and upflow writes included): every launch runs memory v2,
whose entries record their source from the bound task context. The learnings test below
tests v1 code that C2a-2 deletes.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'prov.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


# ---------------------------------------------------------------------------
# save_facts: mandatory provenance (programmer guard, not fail-open dedup)
# ---------------------------------------------------------------------------

async def test_save_facts_missing_provenance_kwarg_raises_typeerror(maker):
    """provenance is keyword-only with no default: omitting it entirely is a
    Python-level signature error (TypeError), distinct from the ValueError the
    top-of-function guard raises for an explicitly-empty {}."""
    from server.orchestrator import memory
    with pytest.raises(TypeError):
        await memory.save_facts([{"content": "x"}])  # type: ignore[call-arg]


async def test_save_facts_empty_provenance_raises_valueerror(maker):
    from server.orchestrator import memory
    with pytest.raises(ValueError):
        await memory.save_facts([{"content": "x"}], provenance={})


async def test_save_facts_none_provenance_raises_valueerror(maker):
    from server.orchestrator import memory
    with pytest.raises(ValueError):
        await memory.save_facts([{"content": "x"}], provenance=None)


async def test_save_facts_guard_fires_before_any_write(maker, monkeypatch):
    """The provenance guard must be unconditional — it must raise before the write
    underneath runs at all, even if that write is broken."""
    from server.orchestrator import memory

    async def boom(facts):
        raise RuntimeError("write exploded")

    monkeypatch.setattr("server.services.memory_compat.save_facts", boom)
    with pytest.raises(ValueError):
        await memory.save_facts([{"content": "x"}], provenance={})


# ---------------------------------------------------------------------------
# learnings: valid_from set on write (source_kind/source_ref already carry
# provenance for this table — no separate provenance column, per the P1 spec)
# ---------------------------------------------------------------------------

