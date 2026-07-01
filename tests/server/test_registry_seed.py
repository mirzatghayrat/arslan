"""Seed integrity: exclusions absent, idempotent, tiers valid, core rows wired."""
import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, SkillPack, Tool, Toolset

EXCLUDED = {"godmode", "obliteratus", "hermes-agent", "hermes-agent-skill-authoring"}


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_create)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_seed_counts_and_exclusions(maker):
    from server.registry.seeder import seed_registry

    await seed_registry()
    async with maker() as s:
        toolsets = (await s.execute(select(Toolset))).scalars().all()
        skills = (await s.execute(select(SkillPack))).scalars().all()
        tools = (await s.execute(select(Tool))).scalars().all()

    assert len(toolsets) == 29
    assert len(skills) >= 70
    assert EXCLUDED.isdisjoint({t.key for t in toolsets})
    assert EXCLUDED.isdisjoint({sk.key for sk in skills})
    assert all(t.tier in ("safe", "orchestrator") for t in toolsets + tools)
    assert all(
        t.status in ("wired", "registered", "absorbed", "infeasible")
        for t in toolsets
    )


@pytest.mark.asyncio
async def test_seed_core_wiring_and_splits(maker):
    from server.registry.seeder import seed_registry

    await seed_registry()
    async with maker() as s:
        ws = await s.get(Toolset, "web_search_scraping")
        assert ws.tier == "safe" and ws.status == "wired"
        for key in ("code_execution", "computer_use", "terminal_processes"):
            assert (await s.get(Toolset, key)).tier == "orchestrator"
        # READ/WRITE split inside File Operations
        assert (await s.get(Tool, "read_file")).tier == "safe"
        assert (await s.get(Tool, "write_file")).tier == "orchestrator"
        assert (await s.get(Tool, "patch")).tier == "orchestrator"
        # absorbed machinery
        assert (await s.get(Toolset, "task_delegation")).status == "absorbed"
        assert (await s.get(Toolset, "memory")).status == "absorbed"
        # coding-delegation skills: registered, orchestrator-only (decision §9)
        for key in ("claude-code", "codex", "opencode"):
            sk = await s.get(SkillPack, key)
            assert sk is not None and sk.tier == "orchestrator"


@pytest.mark.asyncio
async def test_seed_idempotent_and_updates(maker):
    from server.registry.seeder import seed_registry

    await seed_registry()
    # simulate an old classification, re-seed must correct it
    async with maker() as s:
        row = await s.get(Toolset, "web_search_scraping")
        row.tier = "orchestrator"
        await s.commit()
    await seed_registry()
    async with maker() as s:
        assert (await s.get(Toolset, "web_search_scraping")).tier == "safe"
        from sqlalchemy import func
        n = (await s.execute(select(func.count()).select_from(Toolset))).scalar_one()
    assert n == 29
