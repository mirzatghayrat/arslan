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
    WITHOUT the new orchestrator models. The expert-era models went in C7c-5b, so spawns and feedback are
    written out as 0001 had them (before 0002's columns); the rest come from metadata by name."""
    from sqlalchemy import text

    from server.db.models import Base

    original = {"settings", "build_sessions"}
    tables = [t for t in Base.metadata.sorted_tables if t.name in original]
    Base.metadata.create_all(connection, tables=tables)
    connection.execute(text(
        "CREATE TABLE spawns (id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL UNIQUE, "
        "domain_category VARCHAR(50) NOT NULL, system_prompt TEXT NOT NULL)"))
    connection.execute(text(
        "CREATE TABLE feedback (id INTEGER PRIMARY KEY, spawn_id INTEGER NOT NULL REFERENCES spawns (id), "
        "session_id VARCHAR(50) NOT NULL, user_action VARCHAR(20) NOT NULL)"))
