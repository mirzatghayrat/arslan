import sqlalchemy as sa

from server.db.migrations.versions._0008_evolution_proposals import upgrade_sync


def _with_spawns(conn):
    # An install from before C7c-5b (v0.1.64): 0008 makes the table only where `spawns` exists.
    conn.exec_driver_sql("CREATE TABLE spawns (id INTEGER PRIMARY KEY)")


def test_upgrade_creates_table():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _with_spawns(conn)
        upgrade_sync(conn)
        assert "evolution_proposals" in set(sa.inspect(conn).get_table_names())
        cols = {c["name"] for c in sa.inspect(conn).get_columns("evolution_proposals")}
        assert {"id", "spawn_id", "candidate_prompt", "gate_passed", "evidence",
                "status", "created_at", "promoted_at"} <= cols


def test_upgrade_idempotent():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _with_spawns(conn)
        upgrade_sync(conn)
        upgrade_sync(conn)  # no raise
        assert "evolution_proposals" in set(sa.inspect(conn).get_table_names())


def test_a_new_install_without_spawns_gets_no_table():
    """C7c-5b: no Spawn model, so no `spawns`; a table whose foreign key names it would refuse every write."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        upgrade_sync(conn)
        assert "evolution_proposals" not in set(sa.inspect(conn).get_table_names())
