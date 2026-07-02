"""P0 honesty layer: equippable must mean FUNCTIONAL.

A skill with no body injects nothing at dispatch; a toolset with no wired tool resolves to
nothing at Layer 3. Both used to be equippable decoration ("空壳"). Now they stay visible in
the catalog (assignable: false → "catalog") but cannot be equipped.
"""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.registry.service import (
    NotAssignableError,
    assert_assignable,
    safe_menu,
    skill_is_assignable,
    toolset_is_assignable,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def seeded_registry(tmp_path, monkeypatch):
    """Fresh DB with the full seed catalog (same pattern as test_registry_seed.maker)."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_setup)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)

    from server.registry.seeder import seed_registry
    anyio.run(seed_registry)
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

async def test_hollow_skill_not_equippable(seeded_registry):
    # 'notion' is a catalogued integration entry with no body — must be refused.
    with pytest.raises(NotAssignableError, match="catalog-only"):
        await assert_assignable("skill", "notion")


async def test_real_skill_still_equippable(seeded_registry):
    await assert_assignable("skill", "systematic-debugging")  # real body → no raise


async def test_unwired_toolset_not_equippable(seeded_registry):
    # 'spotify' is safe|registered but none of its tools are wired — decoration, refuse.
    with pytest.raises(NotAssignableError, match="no wired tools"):
        await assert_assignable("toolset", "spotify")


async def test_wired_toolset_still_equippable(seeded_registry):
    for key in ("web_search_scraping", "charting", "deck"):
        await assert_assignable("toolset", key)


async def test_safe_menu_lists_only_functional(seeded_registry):
    menu = await safe_menu()
    ts_keys = {t["key"] for t in menu["toolsets"]}
    sk_keys = {s["key"] for s in menu["skills"]}
    # functional ones present
    assert {"web_search_scraping", "charting", "skill_authoring", "deck"} <= ts_keys
    assert "systematic-debugging" in sk_keys and "deck-authoring" in sk_keys
    # decoration absent
    assert "spotify" not in ts_keys and "image_generation" not in ts_keys
    assert "notion" not in sk_keys and "powerpoint" not in sk_keys
