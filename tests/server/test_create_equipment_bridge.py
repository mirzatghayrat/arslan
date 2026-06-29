import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, SpawnCapability
from server.registry import service as registry_service
from server.services import equipment_service, spawn_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'b.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _prep():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_prep)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    return maker


def test_create_uses_drafter_tools_skills_mcps(db, monkeypatch):
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
    spawn_id, name, equipment, intro = anyio.run(lambda: spawn_service.create_from_draft(draft))

    async def _caps():
        async with db() as s:
            rows = (await s.execute(select(SpawnCapability).where(
                SpawnCapability.spawn_id == spawn_id))).scalars().all()
            return {(r.kind, r.ref_key) for r in rows}

    caps = anyio.run(_caps)
    assert ("toolset", "web_search_scraping") in caps
    assert ("skill", "statistical-analysis") in caps
    assert ("toolset", "mcp_7") in caps
    assert ("skill", "mcp_7") not in caps


def test_explicit_equipment_still_wins(db, monkeypatch):
    async def fake_assert(kind, key, **kw):
        return None

    monkeypatch.setattr(registry_service, "assert_assignable", fake_assert)

    async def boom(*a, **k):
        raise AssertionError("curate should not run")

    monkeypatch.setattr(equipment_service, "curate", boom)
    draft = {"name": "x", "domain": "a.b", "capabilities": [],
             "equipment": {"toolsets": ["web_search_scraping"], "skills": []},
             "tools": ["should_be_ignored"]}
    spawn_id, *_ = anyio.run(lambda: spawn_service.create_from_draft(draft))

    async def _caps():
        async with db() as s:
            rows = (await s.execute(select(SpawnCapability).where(
                SpawnCapability.spawn_id == spawn_id))).scalars().all()
            return {(r.kind, r.ref_key) for r in rows}

    caps = anyio.run(_caps)
    assert ("toolset", "web_search_scraping") in caps
    assert ("toolset", "should_be_ignored") not in caps
