"""P0 honesty layer: equippable must mean FUNCTIONAL.

A skill with no body injects nothing at dispatch; a toolset with no wired tool resolves to
nothing at Layer 3. Both used to be equippable decoration ("空壳"). Now they stay visible in
the catalog (assignable: false → "catalog") but cannot be equipped.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.registry.service import (
    safe_menu,
    skill_is_assignable,
    toolset_is_assignable,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def seeded_registry(tmp_path, monkeypatch):
    """Fresh DB with the full seed catalog (same pattern as test_registry_seed.maker)."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)

    from server.registry.seeder import seed_registry
    await seed_registry()
    return m


# ── pure predicates ────────────────────────────────────────────────────────────

def test_skill_predicate_requires_real_body():
    assert skill_is_assignable("safe", "registered", "## Trigger\n真方法论…")
    assert not skill_is_assignable("safe", "registered", None)
    assert not skill_is_assignable("safe", "registered", "")
    assert not skill_is_assignable("safe", "registered", "   \n  ")
    assert not skill_is_assignable("orchestrator", "registered", "body")  # tier still gates


def test_toolset_predicate_requires_wired_tool():
    assert toolset_is_assignable("safe", "wired", has_wired_tool=True)
    assert toolset_is_assignable("safe", "registered", has_wired_tool=True)  # MCP path
    assert not toolset_is_assignable("safe", "registered", has_wired_tool=False)
    assert not toolset_is_assignable("orchestrator", "registered", has_wired_tool=True)


# ── against the seeded registry (real catalog) ────────────────────────────────

# C7c-5a: the write gate (assert_assignable) went with its last write path; the same
# honesty rules are checked on the safe menu, which applies them in its query.
async def _menu_keys() -> tuple[set[str], set[str]]:
    menu = await safe_menu()
    return {t["key"] for t in menu["toolsets"]}, {s["key"] for s in menu["skills"]}


async def test_hollow_skill_not_equippable(seeded_registry):
    # Every seeded safe skill now carries a real body (curation pass), so simulate a
    # hollow row (e.g. a stale import) — bodyless skills must still be refused.
    from server.db.models import SkillPack

    async with seeded_registry() as s:
        s.add(SkillPack(key="hollow-skill", name="hollow", category="general",
                        description="no body", tier="safe", status="registered"))
        await s.commit()
    _, skills = await _menu_keys()
    assert "hollow-skill" not in skills


async def test_real_skill_still_equippable(seeded_registry):
    _, skills = await _menu_keys()
    assert "designed-html-report" in skills  # real body


async def test_unwired_toolset_not_equippable(seeded_registry):
    # 'file_operations' is safe|registered but none of its tools are wired yet
    # (wire-candidate) — until then it's decoration, refuse.
    toolsets, _ = await _menu_keys()
    assert "file_operations" not in toolsets


async def test_wired_toolset_still_equippable(seeded_registry):
    toolsets, _ = await _menu_keys()
    assert {"web_search_scraping", "charting"} <= toolsets


async def test_safe_menu_lists_only_functional(seeded_registry):
    menu = await safe_menu()
    ts_keys = {t["key"] for t in menu["toolsets"]}
    sk_keys = {s["key"] for s in menu["skills"]}
    # functional ones present
    assert {"web_search_scraping", "charting", "skill_authoring"} <= ts_keys
    assert {"designed-html-report", "skill-creator"} <= sk_keys   # C9: the two bundled skills
    # not-yet-wired wire-candidates absent from the equip menu
    assert "file_operations" not in ts_keys
    # C3a: retired outright, gone from the catalog
    assert {"session_search", "task_planning", "skills_management"}.isdisjoint(ts_keys)
    # retired decoration keys gone from the catalog entirely
    assert "spotify" not in ts_keys and "image_generation" not in ts_keys and "deck" not in ts_keys
    assert "notion" not in sk_keys and "powerpoint" not in sk_keys
