"""Unsupported future profiles must be refused before schema/key writes."""
import sqlite3

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from server.db.migrations import runner
from server.db.models import Base
from server.services import storage_boot


@pytest.fixture
def future_profile(tmp_path):
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE schema_version (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        db.executemany("INSERT INTO schema_version VALUES (?, 'synthetic')",
                       [(version,) for version, _ in runner.MIGRATIONS] + [("9999",)])
        db.execute("CREATE TABLE future_data (value TEXT)")
        db.execute("INSERT INTO future_data VALUES ('preserve this fixture')")
    return path


def no_schema_writes(*args, **kwargs):
    raise AssertionError("schema writes reached before compatibility refusal")


def test_direct_migration_refuses_future_ledger_without_changes(future_profile):
    original = future_profile.read_bytes()
    engine = sa.create_engine(f"sqlite:///{future_profile}")
    try:
        with pytest.raises(RuntimeError, match="database_schema_unsupported"):
            with engine.begin() as connection:
                runner.apply_pending(connection)
    finally:
        engine.dispose()
    assert future_profile.read_bytes() == original


async def test_boot_refuses_before_create_all_or_key_bootstrap(future_profile, monkeypatch):
    original = future_profile.read_bytes()
    monkeypatch.setattr(Base.metadata, "create_all", no_schema_writes)
    engine = create_async_engine(f"sqlite+aiosqlite:///{future_profile}")
    try:
        with pytest.raises(RuntimeError, match="database_schema_unsupported"):
            await storage_boot.initialize(engine)
    finally:
        await engine.dispose()
    assert future_profile.read_bytes() == original


def test_cli_refuses_before_create_all(future_profile, monkeypatch):
    original = future_profile.read_bytes()
    monkeypatch.setattr(Base.metadata, "create_all", no_schema_writes)
    with pytest.raises(RuntimeError, match="database_schema_unsupported"):
        runner.main(["--db", str(future_profile)])
    assert future_profile.read_bytes() == original


@pytest.mark.parametrize("schema", [
    "CREATE VIEW schema_version AS SELECT '9999' AS version",
    "CREATE TABLE schema_version (wrong_column TEXT)",
    "CREATE TABLE schema_version (version TEXT); INSERT INTO schema_version VALUES (NULL)",
])
def test_ambiguous_ledger_refuses_read_only(tmp_path, schema):
    path = tmp_path / "ambiguous.db"
    with sqlite3.connect(path) as db:
        db.executescript(schema)
    original = path.read_bytes()
    engine = sa.create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as connection, pytest.raises(RuntimeError, match="database_schema_unsupported"):
            runner.assert_supported_schema(connection)
    finally:
        engine.dispose()
    assert path.read_bytes() == original


def test_fresh_profile_check_creates_no_ledger_or_tables(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    try:
        with engine.begin() as connection:
            runner.assert_supported_schema(connection)
            assert sa.inspect(connection).get_table_names() == []
    finally:
        engine.dispose()
