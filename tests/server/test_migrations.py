"""Verify the initial Alembic migration creates the full schema."""
import pytest
import pytest_asyncio
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

EXPECTED_TABLES = {
    "spawns",
    "chat_messages",
    "feedback",
    "settings",
    "build_sessions",
}


@pytest_asyncio.fixture
async def upgraded_engine(tmp_path):
    """Apply migration 0001 to a temp DB and return its engine."""
    from server.db.migrations.versions import _0001_initial as initial  # type: ignore

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'m.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: initial.upgrade_sync(c))
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_initial_migration_creates_all_tables(upgraded_engine):
    async with upgraded_engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    assert EXPECTED_TABLES.issubset(tables)
