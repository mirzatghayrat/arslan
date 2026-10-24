import pytest_asyncio
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, PersonaSeed


async def test_persona_seed_table_and_fts(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'p.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # FTS virtual table is created by the migration's upgrade_sync, not create_all:
        from server.db.migrations.versions._0015_persona_seeds import upgrade_sync
        await conn.run_sync(upgrade_sync)
    async with maker() as s:
        row = PersonaSeed(slug="game-economy-designer", division="Game Development",
                          name="Game Economy Designer", identity="i", mission="m", rules="r",
                          deliverables="d", workflow="w", success_metrics="s", raw="raw text",
                          source="agency-agents@abc")
        s.add(row)
        await s.flush()
        await s.execute(sa_text("INSERT INTO persona_seeds_fts (rowid, text) VALUES (:r, :t)"),
                        {"r": row.id, "t": "game economy balance monetization"})
        await s.commit()
        hit = (await s.execute(sa_text(
            "SELECT ps.slug FROM persona_seeds_fts f JOIN persona_seeds ps ON ps.id=f.rowid "
            "WHERE f.text MATCH :q"), {"q": "economy"})).scalar_one_or_none()
    assert hit == "game-economy-designer"


@pytest_asyncio.fixture
async def seeded(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'ps.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        from server.db.migrations.versions._0015_persona_seeds import upgrade_sync
        await conn.run_sync(upgrade_sync)
    async with maker() as s:
        for slug, kw in [("game-economy-designer", "game economy balance monetization numerical"),
                         ("seo-copywriter", "seo content writing keywords marketing")]:
            row = PersonaSeed(slug=slug, name=slug, raw=kw, source="x")
            s.add(row)
            await s.flush()
            await s.execute(sa_text("INSERT INTO persona_seeds_fts (rowid, text) VALUES (:r,:t)"),
                            {"r": row.id, "t": kw})
        await s.commit()
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    return maker


async def test_get_by_slugs_resolves_in_order_dropping_unknown(seeded):
    from server.services import persona_seed_service
    out = await persona_seed_service.get_by_slugs(
        ["seo-copywriter", "ghost-slug", "game-economy-designer"])
    assert [o["slug"] for o in out] == ["seo-copywriter", "game-economy-designer"]
    assert await persona_seed_service.get_by_slugs([]) == []


async def test_get_detail_resolves_composed_seeds_from_config(seeded):
    # config.seed_refs persisted at create → SpawnDetailOut.seeds resolved (unknown dropped).
    from server.services import spawn_service
    from server.db.models import Spawn
    async with seeded() as s:
        spawn = Spawn(name="econ-bot", domain_category="game", capabilities=[],
                      system_prompt="x", config={"seed_refs": ["game-economy-designer", "ghost"]})
        s.add(spawn)
        await s.commit()
        await s.refresh(spawn)
        detail = await spawn_service.get_detail(s, spawn.id)
    assert [sd.slug for sd in detail.seeds] == ["game-economy-designer"]


async def test_get_detail_no_seeds_when_config_empty(seeded):
    from server.services import spawn_service
    from server.db.models import Spawn
    async with seeded() as s:
        spawn = Spawn(name="plain", domain_category="x", capabilities=[], system_prompt="x")
        s.add(spawn)
        await s.commit()
        await s.refresh(spawn)
        detail = await spawn_service.get_detail(s, spawn.id)
    assert detail.seeds == []
