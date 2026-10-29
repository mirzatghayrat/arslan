"""0075 (v0.1.64 CAP1c): `capability_finds` goes; `capability_sources`, made by the same 0064, stays."""
from sqlalchemy import create_engine, inspect


def _tables(conn) -> set[str]:
    return set(inspect(conn).get_table_names())


def _indexes(conn) -> set[str]:
    return {row[0] for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='index'")}


def test_0075_drops_the_finds_keeps_the_sources_and_a_second_run_is_a_noop(tmp_path):
    from server.db.migrations.versions._0064_capability_sources import upgrade_sync as create
    from server.db.migrations.versions._0075_drop_capability_finds import upgrade_sync as drop
    engine = create_engine(f"sqlite:///{tmp_path / 'd75.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE mcp_servers (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE skill_packs (key VARCHAR(60) PRIMARY KEY)")
        create(conn)
        conn.exec_driver_sql(
            "INSERT INTO capability_finds (id, need, why, candidate, created_at)"
            " VALUES ('f1', 'formulas', 'job', '{}', '2026-10-01 00:00:00')")
        conn.exec_driver_sql(
            "INSERT INTO capability_sources (id, kind, name, candidate_id, needs, grants, created_at)"
            " VALUES ('s1', 'mcp', 'x', 'c', '{}', '{}', '2026-10-01 00:00:00')")
    with engine.begin() as conn:
        drop(conn)
        assert "capability_finds" not in _tables(conn)
        assert "ix_capability_finds_created_at" not in _indexes(conn)
        assert conn.exec_driver_sql("SELECT id FROM capability_sources").scalars().all() == ["s1"]
        drop(conn)                                               # idempotent
    engine.dispose()


def test_a_new_install_ends_without_the_finds(tmp_path):
    from server.db.migrations import runner
    from server.db.models import Base
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        applied = runner.apply_pending(conn)
        assert "0064" in applied and "0075" in applied
        assert "capability_finds" not in _tables(conn) and "capability_sources" in _tables(conn)
    engine.dispose()
