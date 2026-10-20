"""SAFETY-CRITICAL: the orchestrator-only run_command tool can NEVER reach a spawn.

run_command is an orchestrator-tier tool (whitelisted shell). Spawns operate under
the layer-3 safe-tier gate (wired_tools_for_spawn), and every spawn capability write
goes through the layer-2 gate (assert_assignable). Neither must ever let run_command in.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn, SpawnCapability


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'spawn.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest_asyncio.fixture
async def spawn(maker):
    """A spawn that has been (impossibly) equipped with a run_command toolset row,
    plus the universal safe baseline path. The layer-3 gate must still exclude it."""
    from server.registry.seeder import seed_registry

    await seed_registry()
    async with maker() as s:
        s.add(Spawn(id=1, name="x", domain_category="d", system_prompt="p"))
        # Even if a bad row equips a 'run_command' toolset, the tier/status gate excludes it.
        s.add(SpawnCapability(spawn_id=1, kind="toolset", ref_key="run_command"))
        await s.commit()
    return 1


@pytest.mark.asyncio
async def test_spawn_wired_tools_never_include_run_command(spawn):
    from server.registry import service

    tools = await service.wired_tools_for_spawn(spawn, current_turn=1)
    assert not any(t["key"] == "run_command" for t in tools)


@pytest.mark.asyncio
async def test_run_command_toolset_is_never_assignable(spawn):
    from server.registry import service

    # run_command is not a safe-tier assignable toolset; assert_assignable must reject it.
    # (0.1.63 C1c-1: this went through grant_temporary, deleted with the escalation path.)
    with pytest.raises(service.NotAssignableError):
        await service.assert_assignable("toolset", "run_command")
