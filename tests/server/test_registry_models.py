"""Registry tables exist, constraints hold."""
import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base, SkillPack, Spawn, SpawnCapability, Tool, Toolset


@pytest.fixture
def maker(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'r.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_create)
    return m


@pytest.mark.asyncio
async def test_registry_models_roundtrip(maker):
    async with maker() as s:
        s.add(Toolset(key="web_search_scraping", name="Web Search & Scraping",
                      description="web_search, web_extract", tier="safe", status="wired"))
        s.add(Tool(key="web_search", toolset_key="web_search_scraping",
                   description="Search the web", tier="safe", status="wired"))
        s.add(SkillPack(key="baoyu-infographic", name="baoyu-infographic",
                        category="creative", description="Infographics", tier="safe",
                        status="registered"))
        s.add(Spawn(id=1, name="x", domain_category="d", system_prompt="p"))
        await s.commit()
        s.add(SpawnCapability(spawn_id=1, kind="toolset", ref_key="web_search_scraping"))
        await s.commit()

    async with maker() as s:
        cap = (await s.execute(select(SpawnCapability))).scalar_one()
        assert cap.grant == "permanent" and cap.granted_by == "create"
        assert cap.expires_turn is None
        tool = (await s.execute(select(Tool))).scalar_one()
        assert tool.toolset_key == "web_search_scraping"


@pytest.mark.asyncio
async def test_spawn_capability_unique(maker):
    async with maker() as s:
        s.add(Spawn(id=1, name="x", domain_category="d", system_prompt="p"))
        s.add(SpawnCapability(spawn_id=1, kind="toolset", ref_key="a"))
        await s.commit()
        s.add(SpawnCapability(spawn_id=1, kind="toolset", ref_key="a"))
        with pytest.raises(IntegrityError):
            await s.commit()


def test_migration_0003_idempotent(tmp_path):
    """Applying _0003 twice on a fresh sync SQLite DB is a no-op the second time."""
    from sqlalchemy import create_engine, inspect

    from server.db.migrations.versions import _0001_initial, _0002_orchestrator
    from server.db.migrations.versions import _0003_capability_registry as m3

    engine = create_engine(f"sqlite:///{tmp_path/'mig.db'}")
    with engine.begin() as conn:
        _0001_initial.upgrade_sync(conn)
        _0002_orchestrator.upgrade_sync(conn)
        m3.upgrade_sync(conn)
        m3.upgrade_sync(conn)  # idempotent
        names = set(inspect(conn).get_table_names())
        uqs = inspect(conn).get_unique_constraints("spawn_capabilities")
    assert {"toolsets", "tools", "skill_packs", "spawn_capabilities"} <= names
    assert any(
        set(uq["column_names"]) == {"spawn_id", "kind", "ref_key"} for uq in uqs
    )


def test_migration_0003_downgrade_roundtrip(tmp_path):
    """Downgrade of _0003 removes the four capability-registry tables; a second
    downgrade is idempotent and must not raise."""
    from sqlalchemy import create_engine, inspect

    from server.db.migrations.versions import _0001_initial, _0002_orchestrator
    from server.db.migrations.versions import _0003_capability_registry as m3

    REGISTRY_TABLES = {"toolsets", "tools", "skill_packs", "spawn_capabilities"}

    engine = create_engine(f"sqlite:///{tmp_path/'mig.db'}")
    with engine.begin() as conn:
        _0001_initial.upgrade_sync(conn)
        _0002_orchestrator.upgrade_sync(conn)
        m3.upgrade_sync(conn)
        m3.downgrade_sync(conn)
        # idempotent: a second downgrade must not raise
        m3.downgrade_sync(conn)
        names = set(inspect(conn).get_table_names())

    assert not (REGISTRY_TABLES & names)  # all four tables gone
