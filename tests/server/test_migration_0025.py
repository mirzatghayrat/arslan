import pytest
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_0025_creates_tables_and_column():
    # Hermetic: own in-memory engine (no global-DB singletons → no test-ordering
    # fragility). Mirrors real boot order — create_all first, then the migration —
    # so the FTS self-heal path (base table present, shadow missing) is exercised.
    from server.db.models import Base
    from server.db.migrations.versions._0025_second_brain_rebuild import upgrade_sync

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(upgrade_sync)
            await conn.run_sync(upgrade_sync)  # idempotent second run must not raise

            cols = {r[1] for r in (await conn.exec_driver_sql("PRAGMA table_info(user_facts)"))}
            assert "confidence" in cols
            tables = {r[0] for r in (await conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"))}
            assert "learnings" in tables
            assert "learnings_fts" in tables
            assert "brain_usage" in tables
            idx = {r[1] for r in (await conn.exec_driver_sql("PRAGMA index_list(brain_usage)"))}
            assert any("brain_usage" in name for name in idx)
    finally:
        await engine.dispose()
