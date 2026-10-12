"""0.1.61 §C1/§C4/§C7: the columns skills v2 keeps on skill_packs and skill_candidates."""
from __future__ import annotations

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
    assert ids.count("0070") == 1 and ids == sorted(ids)
    fn = dict(runner.MIGRATIONS)["0070"]
    assert fn.__module__.endswith("_0070_skills_v2")
