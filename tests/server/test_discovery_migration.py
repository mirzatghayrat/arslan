from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


async def test_migration_0012_creates_table(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'d12.db'}")

    from server.db.models import Base
    from server.db.migrations.versions._0012_discovery_candidates import upgrade_sync
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(upgrade_sync)
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))

    assert "discovery_candidates" in tables


async def test_candidate_model_roundtrip(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'d12b.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from server.db.models import Base, DiscoveryCandidate
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with m() as s:
        s.add(DiscoveryCandidate(full_name="o/r", html_url="u", snapshot={"repo": {"full_name": "o/r"}}))
        await s.commit()
    async with m() as s:
        row = (await s.execute(select(DiscoveryCandidate))).scalar_one()
        name, snap = row.full_name, row.snapshot
    assert name == "o/r" and snap["repo"]["full_name"] == "o/r"
