"""SAFETY-CRITICAL: the orchestrator-only run_command tool is never on the safe menu.

run_command is an orchestrator-tier tool (whitelisted shell). The safe menu (what the MCP
server lists for outside clients) must never offer it. The spawn write gate
(assert_assignable) went in C7c-5a with its last write path; the layer-3 gate,
wired_tools_for_spawn, went with the dispatcher in C7b-4/6, v0.1.63.
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
    """The real seeded registry, so safe_menu judges run_command by its real tier."""
    from server.registry.seeder import seed_registry

    await seed_registry()


@pytest.mark.asyncio
async def test_run_command_toolset_is_never_on_the_safe_menu(seeded):
    from server.registry import service

    menu = await service.safe_menu()
    keys = {t["key"] for t in menu["toolsets"]}
    assert keys, "positive control: the seeded registry has safe toolsets"
    assert "run_command" not in keys
