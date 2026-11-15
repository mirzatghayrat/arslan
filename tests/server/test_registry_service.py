"""safe_menu: the permission model's hard gate (spec §2, test #4; assert_assignable went in C7c-5a)."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'rs.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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
async def test_safe_menu_rejects_orchestrator_and_unknown(seeded):
    # C7c-5a: was test_assert_assignable_rejects_orchestrator_and_unknown; the gate went
    # with its last write path, and the safe menu applies the same rules.
    from server.registry import service

    menu = await service.safe_menu()
    toolsets = {t["key"] for t in menu["toolsets"]}
    skills = {s["key"] for s in menu["skills"]}
    assert "web_search_scraping" in toolsets   # ok
    assert "designed-html-report" in skills    # ok
    assert {"code_execution", "terminal_processes", "no-such-key", "memory"}.isdisjoint(toolsets)
    assert "claude-code" not in skills          # retired (C9): unknown now
