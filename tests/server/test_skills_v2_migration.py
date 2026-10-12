"""0.1.61 §C1/§C4/§C7: the columns skills v2 keeps on skill_packs and skill_candidates."""
from __future__ import annotations

import pytest
import sqlalchemy as sa

from server.db.models import SkillCandidate, SkillPack

OLD_SKILL_PACKS = (
    "CREATE TABLE skill_packs (key VARCHAR(60) PRIMARY KEY, name VARCHAR(100) NOT NULL, "
    "category VARCHAR(40) NOT NULL, description TEXT NOT NULL, tier VARCHAR(20) NOT NULL, "
    "status VARCHAR(20) NOT NULL, body TEXT, enabled BOOLEAN NOT NULL DEFAULT 1, source_id VARCHAR(36))")
OLD_CANDIDATES = (
    "CREATE TABLE skill_candidates (id INTEGER PRIMARY KEY, key VARCHAR(60) NOT NULL, name VARCHAR(100) NOT NULL, "
    "category VARCHAR(40) NOT NULL, description TEXT NOT NULL, body TEXT NOT NULL, source VARCHAR(20) NOT NULL, "
    "status VARCHAR(20) NOT NULL, samples JSON, evidence JSON, created_at DATETIME, promoted_at DATETIME)")


def _columns(conn, table):
    return {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}


def test_migration_0070_adds_the_columns_once_and_marks_existing_imports(tmp_path):
    from server.db.migrations.versions import _0070_skills_v2 as m
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql(OLD_SKILL_PACKS)
        conn.exec_driver_sql(OLD_CANDIDATES)
        conn.exec_driver_sql("INSERT INTO skill_packs (key, name, category, description, tier, status, body) VALUES "
                             "('handoff', 'handoff', 'imported', 'd', 'safe', 'registered', 'b'), "
                             "('plan', 'plan', 'software-development', 'd', 'safe', 'registered', 'b')")
        m.upgrade_sync(conn)
        m.upgrade_sync(conn)                                   # idempotent
        assert {"origin", "folder", "text_sha256", "scan", "frontmatter", "invocable", "pinned", "local_only",
                "license_spdx", "license_sha256", "license_accepted_at"} <= _columns(conn, "skill_packs")
        assert {"conversation_id", "files"} <= _columns(conn, "skill_candidates")
        rows = conn.exec_driver_sql(
            "SELECT key, origin, invocable, pinned, local_only FROM skill_packs ORDER BY key").fetchall()
    assert rows == [("handoff", "imported", 1, 0, 0), ("plan", "saved", 1, 0, 0)]


def test_migration_0070_downgrade_takes_the_columns_away(tmp_path):
    from server.db.migrations.versions import _0070_skills_v2 as m
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql(OLD_SKILL_PACKS)
        conn.exec_driver_sql(OLD_CANDIDATES)
        m.upgrade_sync(conn)
        m.downgrade_sync(conn)
        assert "origin" not in _columns(conn, "skill_packs")
        assert "files" not in _columns(conn, "skill_candidates")


async def test_a_new_row_gets_the_defaults(execution_db):
    async with execution_db() as db:
        db.add(SkillPack(key="tidy", name="Tidy", category="x", description="d", tier="safe",
                         status="registered", body="# Tidy"))
        db.add(SkillCandidate(key="draft", name="Draft", category="saved", description="d", body="b"))
        await db.commit()
        pack = await db.get(SkillPack, "tidy")
        cand = (await db.execute(sa.select(SkillCandidate))).scalar_one()
    assert (pack.origin, pack.invocable, pack.pinned, pack.local_only) == ("saved", True, False, False)
    assert (pack.folder, pack.scan, pack.license_sha256) == (None, None, None)
    assert (cand.conversation_id, cand.files) == (None, None)


def test_migration_0070_sits_in_ascending_order_whatever_its_neighbours():
    """Ruling H: 0068 (PR 4), 0069 (PR 3) and 0071 (PR 5) are added by other PRs in the same places.
    Where 0070 is inserted is checked on its own, not through a hard-coded neighbour: the registry is
    ascending, holds 0070 once, and 0070's function comes from its own module."""
    from server.db.migrations import runner
    ids = [vid for vid, _ in runner.MIGRATIONS]
    assert ids.count("0070") == 1, "insert new ids in numeric position (Ruling H)"
    assert ids == sorted(ids), "insert new ids in numeric position (Ruling H)"
    fn = dict(runner.MIGRATIONS)["0070"]
    assert fn.__module__.endswith("_0070_skills_v2")


NEW = {
    "skill_packs": {"origin", "folder", "text_sha256", "scan", "frontmatter", "invocable", "pinned",
                    "local_only", "license_spdx", "license_sha256", "license_accepted_at"},
    "skill_candidates": {"conversation_id", "files"},
}


def _shape(conn, table):
    """(type, NOT NULL, default without its quotes) for each column: '1' and 1 are one default."""
    return {r[1]: (r[2], r[3], None if r[4] is None else str(r[4]).strip("'"))
            for r in conn.exec_driver_sql(f"PRAGMA table_info({table})")}


def test_migration_0070_and_create_all_build_the_same_columns(tmp_path):
    """A new install gets the columns from create_all, an upgrade from the migration. Where they
    differ (a type, NOT NULL, a default) the two kinds of install behave differently."""
    from server.db.migrations.versions import _0070_skills_v2 as m
    from server.db.models import Base
    made = sa.create_engine(f"sqlite:///{tmp_path / 'made.db'}")
    with made.begin() as conn:
        Base.metadata.create_all(conn)
        built = {t: _shape(conn, t) for t in NEW}
    old = sa.create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with old.begin() as conn:
        conn.exec_driver_sql(OLD_SKILL_PACKS)
        conn.exec_driver_sql(OLD_CANDIDATES)
        m.upgrade_sync(conn)
        migrated = {t: _shape(conn, t) for t in NEW}
    for table, names in NEW.items():
        assert names <= set(built[table]) and names <= set(migrated[table])
        assert {n: migrated[table][n] for n in names} == {n: built[table][n] for n in names}


def test_migration_0070_downgrade_gives_back_exactly_the_old_tables(tmp_path):
    from server.db.migrations.versions import _0070_skills_v2 as m
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql(OLD_SKILL_PACKS)
        conn.exec_driver_sql(OLD_CANDIDATES)
        conn.exec_driver_sql("INSERT INTO skill_packs (key, name, category, description, tier, status, body) "
                             "VALUES ('handoff', 'handoff', 'imported', 'd', 'safe', 'registered', 'b')")
        before = {t: _columns(conn, t) for t in NEW}
        rows = conn.exec_driver_sql("SELECT * FROM skill_packs").fetchall()
        m.upgrade_sync(conn)
        m.downgrade_sync(conn)
        assert {t: _columns(conn, t) for t in NEW} == before
        assert conn.exec_driver_sql("SELECT * FROM skill_packs").fetchall() == rows


def test_migration_0070_second_run_leaves_a_row_that_has_moved_on(tmp_path):
    """The backfill's `AND origin = 'saved'`: a re-run never takes an origin the app set since."""
    from server.db.migrations.versions import _0070_skills_v2 as m
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql(OLD_SKILL_PACKS)
        conn.exec_driver_sql(OLD_CANDIDATES)
        conn.exec_driver_sql("INSERT INTO skill_packs (key, name, category, description, tier, status) "
                             "VALUES ('x', 'x', 'imported', 'd', 'safe', 'registered')")
        m.upgrade_sync(conn)
        conn.exec_driver_sql("UPDATE skill_packs SET origin = 'agents' WHERE key = 'x'")
        m.upgrade_sync(conn)
        assert conn.exec_driver_sql("SELECT origin FROM skill_packs").scalar() == "agents"


def test_migration_0070_finishes_a_run_that_died_after_some_columns(tmp_path):
    """DDL is not rolled back by pysqlite: a run can stop with only some columns added."""
    from server.db.migrations.versions import _0070_skills_v2 as m
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql(OLD_SKILL_PACKS)
        conn.exec_driver_sql(OLD_CANDIDATES)
        conn.exec_driver_sql("INSERT INTO skill_packs (key, name, category, description, tier, status) "
                             "VALUES ('x', 'x', 'imported', 'd', 'safe', 'registered')")
        conn.exec_driver_sql("ALTER TABLE skill_packs ADD COLUMN origin VARCHAR(20) NOT NULL DEFAULT 'saved'")
        m.upgrade_sync(conn)
        assert NEW["skill_packs"] <= _columns(conn, "skill_packs")
        assert conn.exec_driver_sql("SELECT origin FROM skill_packs").scalar() == "imported"


def test_migration_0070_stays_loud_on_a_database_without_the_tables(tmp_path):
    """Like 0062 and 0064: no quiet skip. Boot runs create_all before the migrations, so the tables are there."""
    from server.db.migrations.versions import _0070_skills_v2 as m
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn, pytest.raises(sa.exc.OperationalError):
        m.upgrade_sync(conn)
