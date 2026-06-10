"""safe_menu/assert_assignable: the permission model's hard gates (spec §2, test #4)."""
import anyio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn, SpawnCapability


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'rs.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_setup)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest_asyncio.fixture
async def seeded(maker):
    from server.registry.seeder import seed_registry

    await seed_registry()
    return maker


@pytest.mark.asyncio
async def test_safe_menu_contains_zero_unsafe_items(seeded):
    """Property over the WHOLE seeded registry: layer-1 invisibility."""
    from server.registry import service

    menu = await service.safe_menu()
    assert menu["toolsets"] and menu["skills"]
    for item in menu["toolsets"] + menu["skills"]:
        assert item["tier"] == "safe"
        assert item["status"] in ("wired", "registered")  # no absorbed/infeasible
    keys = {i["key"] for i in menu["toolsets"]}
    assert "code_execution" not in keys
    assert "terminal_processes" not in keys
    assert "computer_use" not in keys
    assert "task_delegation" not in keys          # absorbed
    skill_keys = {i["key"] for i in menu["skills"]}
    assert {"claude-code", "codex", "opencode"}.isdisjoint(skill_keys)


@pytest.mark.asyncio
async def test_assert_assignable_rejects_orchestrator_and_unknown(seeded):
    from server.registry import service

    await service.assert_assignable("toolset", "web_search_scraping")  # ok
    await service.assert_assignable("skill", "baoyu-infographic")      # ok
    with pytest.raises(service.NotAssignableError):
        await service.assert_assignable("toolset", "code_execution")
    with pytest.raises(service.NotAssignableError):
        await service.assert_assignable("toolset", "terminal_processes")
    with pytest.raises(service.NotAssignableError):
        await service.assert_assignable("skill", "claude-code")
    with pytest.raises(service.NotAssignableError):
        await service.assert_assignable("toolset", "no-such-key")
    with pytest.raises(service.NotAssignableError):
        await service.assert_assignable("toolset", "memory")  # absorbed


@pytest.mark.asyncio
async def test_wired_tools_for_spawn_gate(seeded, maker):
    """Layer 3 source of truth: equipped ∩ tool.tier==safe ∩ tool.status==wired."""
    from server.registry import service

    async with maker() as s:
        s.add(Spawn(id=1, name="x", domain_category="d", system_prompt="p"))
        s.add(SpawnCapability(spawn_id=1, kind="toolset", ref_key="web_search_scraping"))
        s.add(SpawnCapability(spawn_id=1, kind="toolset", ref_key="file_operations"))
        await s.commit()

    tools = await service.wired_tools_for_spawn(1, current_turn=0)
    keys = {t["key"] for t in tools}
    assert keys == {"web_search", "web_extract"}  # file ops not wired; write_file never


@pytest.mark.asyncio
async def test_temporary_grant_expiry(seeded, maker):
    from server.registry import service

    async with maker() as s:
        s.add(Spawn(id=1, name="x", domain_category="d", system_prompt="p"))
        s.add(SpawnCapability(spawn_id=1, kind="toolset", ref_key="web_search_scraping",
                              grant="temporary", granted_by="escalation", expires_turn=5))
        await s.commit()

    assert {t["key"] for t in await service.wired_tools_for_spawn(1, current_turn=5)} == {
        "web_search", "web_extract"
    }
    assert await service.wired_tools_for_spawn(1, current_turn=6) == []


@pytest.mark.asyncio
async def test_grant_temporary_is_safe_only(seeded, maker):
    """Spec test #3: temp grants can ONLY be safe-subset; execution tier raises."""
    from server.registry import service

    async with maker() as s:
        s.add(Spawn(id=1, name="x", domain_category="d", system_prompt="p"))
        await s.commit()

    await service.grant_temporary(1, "web_search_scraping", current_turn=1)
    for key in ("code_execution", "terminal_processes", "computer_use"):
        with pytest.raises(service.NotAssignableError):
            await service.grant_temporary(1, key, current_turn=1)
