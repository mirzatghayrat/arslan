from sqlalchemy import create_engine, inspect
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


def _tables(conn) -> set[str]:
    return set(inspect(conn).get_table_names())


def test_0074_drops_the_saved_catalog_and_a_second_run_is_a_noop(tmp_path):
    """CAP1b: an upgraded install loses the table with its rows; nothing else is touched."""
    from server.db.migrations.versions._0012_discovery_candidates import upgrade_sync as create
    from server.db.migrations.versions._0074_drop_discovery_candidates import upgrade_sync as drop
    engine = create_engine(f"sqlite:///{tmp_path / 'd74.db'}")
    with engine.begin() as conn:
        create(conn)
        conn.exec_driver_sql("CREATE TABLE neighbour (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql(
            "INSERT INTO discovery_candidates (full_name, html_url, snapshot) VALUES ('o/r', 'u', '{}')")
    with engine.begin() as conn:
        drop(conn)
        assert "discovery_candidates" not in _tables(conn) and "neighbour" in _tables(conn)
        drop(conn)                                               # idempotent
        assert "neighbour" in _tables(conn)
    engine.dispose()


def test_a_new_install_ends_without_the_saved_catalog(tmp_path):
    """0012 still creates it on a new install; 0074 drops it in the same boot."""
    from server.db.migrations import runner
    from server.db.models import Base
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        applied = runner.apply_pending(conn)
        assert "0012" in applied and "0074" in applied
        assert "discovery_candidates" not in _tables(conn)
    engine.dispose()
