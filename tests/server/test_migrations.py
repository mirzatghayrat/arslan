"""Verify the initial Alembic migration creates the full schema."""
import pytest
import pytest_asyncio
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

EXPECTED_TABLES = {
    "settings",
    "arslan_messages",
    "runs",
}
# C7c-5b (v0.1.64): the expert-era models went, so 0001's create_all makes none of their tables.
GONE_TABLES = {"spawns", "chat_messages", "feedback"}


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
    assert not GONE_TABLES & tables
