import sqlalchemy as sa

from server.db.migrations.versions._0008_evolution_proposals import upgrade_sync


def test_upgrade_creates_table():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        upgrade_sync(conn)
        assert "evolution_proposals" in set(sa.inspect(conn).get_table_names())
        cols = {c["name"] for c in sa.inspect(conn).get_columns("evolution_proposals")}
        assert {"id", "spawn_id", "candidate_prompt", "gate_passed", "evidence",
                "status", "created_at", "promoted_at"} <= cols


def test_upgrade_idempotent():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        upgrade_sync(conn)
        upgrade_sync(conn)  # no raise
        assert "evolution_proposals" in set(sa.inspect(conn).get_table_names())
