import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, SpawnCapability
from server.registry import service as registry_service
from server.services import equipment_service, spawn_service


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'b.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    return maker


async def _persisted_caps(maker, spawn_id):
    """Return the set of (kind, ref_key) SpawnCapability rows for a spawn."""

    async with maker() as s:
        rows = (await s.execute(select(SpawnCapability).where(
            SpawnCapability.spawn_id == spawn_id))).scalars().all()
        return {(r.kind, r.ref_key) for r in rows}


async def test_create_uses_drafter_tools_skills_mcps(db, monkeypatch):
    async def fake_assert(kind, key, **kw):
        assert kind in ("toolset", "skill")
        return None

    monkeypatch.setattr(registry_service, "assert_assignable", fake_assert)

    async def boom(*a, **k):
        raise AssertionError("curate should not run when drafter equipment is present")

    monkeypatch.setattr(equipment_service, "curate", boom)

    draft = {"name": "numeric-pal", "domain": "game.numerical",
             "capabilities": ["balance"], "persona_role": "数值策划",
             "tools": ["web_search_scraping"], "skills": ["statistical-analysis"],
             "mcps": ["mcp_7"]}
    spawn_id, name, equipment, intro = await spawn_service.create_from_draft(draft)

    caps = await _persisted_caps(db, spawn_id)
    assert ("toolset", "web_search_scraping") in caps
    assert ("skill", "statistical-analysis") in caps
    assert ("toolset", "mcp_7") in caps
    assert ("skill", "mcp_7") not in caps


async def test_explicit_equipment_still_wins(db, monkeypatch):
    async def fake_assert(kind, key, **kw):
        return None

    monkeypatch.setattr(registry_service, "assert_assignable", fake_assert)

    async def boom(*a, **k):
        raise AssertionError("curate should not run")

    monkeypatch.setattr(equipment_service, "curate", boom)
    draft = {"name": "x", "domain": "a.b", "capabilities": [],
             "equipment": {"toolsets": ["web_search_scraping"], "skills": []},
             "tools": ["should_be_ignored"]}
    spawn_id, *_ = await spawn_service.create_from_draft(draft)

    caps = await _persisted_caps(db, spawn_id)
    assert ("toolset", "web_search_scraping") in caps
    assert ("toolset", "should_be_ignored") not in caps


async def test_curate_fallback_folds_mcps(db, monkeypatch):
    # No explicit equipment AND no drafter tools/skills/mcps keys at all → fall
    # through to curate. Curate's mcps must be folded into the toolsets bucket
    # (persisted kind="toolset" with the mcp_ key), not dropped or kind="skill"/"mcp".
    async def fake_assert(kind, key, **kw):
        assert kind in ("toolset", "skill")
        return None

    monkeypatch.setattr(registry_service, "assert_assignable", fake_assert)

    async def fake_curate(need):
        return {"toolsets": ["web_search_scraping"],
                "skills": ["statistical-analysis"],
                "mcps": ["mcp_9"], "gaps": []}

    monkeypatch.setattr(equipment_service, "curate", fake_curate)

    draft = {"name": "fallback-pal", "domain": "research.general",
             "capabilities": ["research"], "persona_role": "researcher"}
    spawn_id, *_ = await spawn_service.create_from_draft(draft)

    caps = await _persisted_caps(db, spawn_id)
    assert ("toolset", "web_search_scraping") in caps
    assert ("skill", "statistical-analysis") in caps
    assert ("toolset", "mcp_9") in caps
    assert ("skill", "mcp_9") not in caps
    assert ("mcp", "mcp_9") not in caps
