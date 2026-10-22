"""SAFETY-CRITICAL: the orchestrator-only run_command tool can NEVER reach a spawn.

run_command is an orchestrator-tier tool (whitelisted shell). Every spawn capability
write goes through the layer-2 gate (assert_assignable), which must never let it in.
(The layer-3 gate, wired_tools_for_spawn, went with the dispatcher in C7b-4/6, v0.1.63:
no spawn turn calls tools any more.)
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'spawn.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest_asyncio.fixture
async def seeded(maker):
    """The real seeded registry, so assert_assignable judges run_command by its real tier."""
    from server.registry.seeder import seed_registry

    await seed_registry()


@pytest.mark.asyncio
async def test_run_command_toolset_is_never_assignable(seeded):
    from server.registry import service

    # run_command is not a safe-tier assignable toolset; assert_assignable must reject it.
    # (0.1.63 C1c-1: this went through grant_temporary, deleted with the escalation path.)
    with pytest.raises(service.NotAssignableError):
        await service.assert_assignable("toolset", "run_command")
