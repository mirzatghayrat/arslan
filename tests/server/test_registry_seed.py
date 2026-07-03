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

    assert len(toolsets) == 9
    assert len(skills) == 55
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
        # READ/WRITE split inside File Operations
        assert (await s.get(Tool, "read_file")).tier == "safe"
        assert (await s.get(Tool, "write_file")).tier == "orchestrator"
        assert (await s.get(Tool, "patch")).tier == "orchestrator"
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
    assert n == 9


@pytest.mark.asyncio
async def test_seed_retires_removed_keys_but_spares_user_rows(maker):
    """Retirement: a previously-seeded retired key is deleted on re-seed; user rows
    (mcp_* toolsets, imported/promoted skills) survive because only the literal
    retirement lists are ever deleted."""
    from server.registry.seeder import seed_registry

    # simulate an old DB: retired seed rows + user-created rows
    async with maker() as s:
        s.add(Toolset(key="spotify", name="Spotify", description="old seed",
                      tier="safe", status="registered"))
        s.add(Tool(key="spotify_search", toolset_key="spotify", description="old",
                   tier="safe", status="registered", input_schema={}))
        s.add(SkillPack(key="notion", name="notion", category="productivity",
                        description="old seed", tier="safe", status="registered"))
        s.add(Toolset(key="mcp_x", name="User MCP", description="user-added",
                      tier="safe", status="registered"))
        s.add(Tool(key="mcp_x__do", toolset_key="mcp_x", description="user tool",
                   tier="safe", status="wired", input_schema={}))
        s.add(SkillPack(key="my-imported-skill", name="my-imported-skill",
                        category="imported", description="user import",
                        tier="safe", status="registered", body="## Trigger\nx" * 30))
        await s.commit()

    await seed_registry()
    await seed_registry()  # idempotent on absent keys

    async with maker() as s:
        assert await s.get(Toolset, "spotify") is None
        assert await s.get(Tool, "spotify_search") is None
        assert await s.get(SkillPack, "notion") is None
        # user rows untouched
        assert (await s.get(Toolset, "mcp_x")).name == "User MCP"
        assert (await s.get(Tool, "mcp_x__do")).status == "wired"
        assert (await s.get(SkillPack, "my-imported-skill")).body
