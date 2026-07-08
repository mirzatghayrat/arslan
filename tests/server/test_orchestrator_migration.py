"""Migration 0002 adds orchestrator tables + reserved columns to an 0001 DB."""
import pytest
import pytest_asyncio
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from server.db.migrations.versions import _0002_orchestrator as m2

NEW_TABLES = {"arslan_messages", "arslan_summaries", "user_facts", "router_decisions"}


@pytest_asyncio.fixture
async def engine(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'mig.db'}")
    yield eng
    await eng.dispose()


@pytest.mark.asyncio
async def test_0002_adds_tables_and_columns(engine):
    # Start from a bare 0001 schema built WITHOUT the new models, to prove 0002 does the work.
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: _create_0001_only(c))
        await conn.run_sync(lambda c: m2.upgrade_sync(c))

    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        spawn_cols = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("spawns")}
        )
        fb_cols = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("feedback")}
        )
    assert NEW_TABLES.issubset(tables)
    assert "level" in spawn_cols and "memory_facts" in spawn_cols
    assert "quality_signal" in fb_cols


@pytest.mark.asyncio
async def test_0002_downgrade_roundtrip(engine):
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: _create_0001_only(c))
        await conn.run_sync(lambda c: m2.upgrade_sync(c))
        await conn.run_sync(lambda c: m2.downgrade_sync(c))
        # idempotent: a second downgrade must not raise
        await conn.run_sync(lambda c: m2.downgrade_sync(c))

    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        spawn_cols = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("spawns")}
        )
        fb_cols = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("feedback")}
        )
    assert not (NEW_TABLES & tables)            # new tables gone
    assert "level" not in spawn_cols and "memory_facts" not in spawn_cols
    assert "quality_signal" not in fb_cols


def _create_0001_only(connection):
    """Build only the original 0001 tables (spawns/chat_messages/feedback/settings/build_sessions)
    WITHOUT the new orchestrator models, by selecting them from metadata by name."""
    from server.db.models import Base

    original = {"spawns", "chat_messages", "feedback", "settings", "build_sessions"}
    tables = [t for t in Base.metadata.sorted_tables if t.name in original]
    Base.metadata.create_all(connection, tables=tables)
