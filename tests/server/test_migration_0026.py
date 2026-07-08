import pytest
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_0026_creates_notes():
    from server.db.models import Base
    from server.db.migrations.versions._0026_notes import upgrade_sync
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(upgrade_sync)
            await conn.run_sync(upgrade_sync)  # idempotent
            tables = {r[0] for r in (await conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"))}
            assert "notes" in tables and "notes_fts" in tables
            cols = {r[1] for r in (await conn.exec_driver_sql("PRAGMA table_info(notes)"))}
            assert {"id", "title", "content", "tags", "created_at", "updated_at"} <= cols
    finally:
        await engine.dispose()
