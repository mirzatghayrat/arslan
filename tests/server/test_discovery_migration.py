from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine


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
