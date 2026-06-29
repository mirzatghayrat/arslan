import anyio
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base, PersonaSeed


def test_persona_seed_table_and_fts(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'p.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _run():
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
            return hit
    assert anyio.run(_run) == "game-economy-designer"
