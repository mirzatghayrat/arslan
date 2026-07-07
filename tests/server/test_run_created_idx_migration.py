import anyio
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from server.db.models import Base
from server.db.migrations.versions._0022_run_created_idx import upgrade_sync


def test_0022_adds_created_at_index(tmp_path):
    async def _run():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'i.db'}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(upgrade_sync)
            idx = await conn.run_sync(lambda c: {i["name"] for i in inspect(c).get_indexes("runs")})
        await engine.dispose()
        return idx
    assert "ix_runs_created_at" in anyio.run(_run)
