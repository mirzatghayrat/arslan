from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from server.db.models import Base
from server.db.migrations.versions._0021_run_detail import upgrade_sync


async def test_0021_adds_run_detail_columns(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'m.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(upgrade_sync)
        cols = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("runs")})
    await engine.dispose()
    for c in ["model", "provider", "tokens_in", "tokens_out", "tokens_estimated",
              "error_kind", "error_text", "system_prompt", "injected_kb"]:
        assert c in cols
