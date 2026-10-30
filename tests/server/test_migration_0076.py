"""0076 (v0.1.64, PRJ0's table drop): `project_habits` and `project_levels.habit` go; the levels stay.

Booted the way the app boots (storage_boot.initialize on build_engine, so foreign keys are on), on
an install from before this PR and on a new one.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.migrations import runner
from server.db.migrations.versions import _0063_project_levels as m0063
from server.db.migrations.versions import _0076_drop_project_habits as m0076
from server.db.models import ProjectLevel
from server.db.session import build_engine
from server.services import storage_boot

#: `project_levels` as create_all made it from the model before this PR: `habit` NOT NULL, with no
#: default in the table (the model's default was Python-side).
OLD_LEVELS = """CREATE TABLE project_levels (
    id VARCHAR(36) NOT NULL, project_id VARCHAR(36) NOT NULL, position INTEGER NOT NULL,
    name VARCHAR(120) NOT NULL, description VARCHAR(300) NOT NULL, band VARCHAR(10) NOT NULL,
    clear_condition VARCHAR(400) NOT NULL, state VARCHAR(10) NOT NULL, habit BOOLEAN NOT NULL,
    started_at DATETIME, cleared_at DATETIME, PRIMARY KEY (id),
    CONSTRAINT ck_project_level_band CHECK (band IN ('shaping','doing','done')),
    CONSTRAINT ck_project_level_state CHECK (state IN ('todo','current','cleared')),
    FOREIGN KEY(project_id) REFERENCES projects (id))"""


async def _boot(db_path) -> None:
    engine = build_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await storage_boot.initialize(engine)
    finally:
        await engine.dispose()


def _shape(db_path) -> tuple[set[str], set[str]]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return (set(sa.inspect(conn).get_table_names()),
                    {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(project_levels)")})
    finally:
        engine.dispose()


async def _before_0076(db_path) -> None:
    """An install as main left it before this PR. A real first launch, so the views and triggers a
    real install has are there (SQLite checks them all again after DROP COLUMN). Then the old model's
    `project_levels`, 0063's `project_habits`, 0076 forgotten, and a project with a level, a
    checkpoint and a rule."""
    await _boot(db_path)
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            assert conn.execute(sa.text("SELECT count(*) FROM sqlite_master WHERE type = 'view'")).scalar()
            assert conn.execute(sa.text("SELECT count(*) FROM sqlite_master WHERE type = 'trigger'")).scalar()
            conn.exec_driver_sql("DROP TABLE project_levels")
            conn.exec_driver_sql(OLD_LEVELS)
            m0063.upgrade_sync(conn)        # makes project_habits; project_levels exists, so it stays as above
            conn.exec_driver_sql("DELETE FROM schema_version WHERE version = '0076'")
            conn.exec_driver_sql(
                "INSERT INTO projects (id, owner_id, name, kind, summary, collection_ids, status, version,"
                " created_at, updated_at) VALUES ('p1', 'local', 'Sample', 'general', '', '[]', 'active', 1,"
                " '2026-10-01 00:00:00', '2026-10-01 00:00:00')")
            conn.exec_driver_sql(
                "INSERT INTO project_levels (id, project_id, position, name, description, band,"
                " clear_condition, state, habit) VALUES ('l1', 'p1', 0, 'Look approved', '', 'shaping',"
                " 'You approve the key art', 'current', 1)")
            conn.exec_driver_sql(
                "INSERT INTO project_checkpoints (id, level_id, position, text, state)"
                " VALUES ('c1', 'l1', 0, 'Key art', 'todo')")
            conn.exec_driver_sql(
                "INSERT INTO project_habits (id, owner_id, kind, text, sources, enabled, created_at)"
                " VALUES ('h1', 'local', 'plan_rule', 'Always a look stage', '[]', 1, '2026-10-01 00:00:00')")
    finally:
        engine.dispose()


async def test_an_install_from_before_loses_the_rules_and_the_column_and_keeps_its_levels(tmp_path):
    db = tmp_path / "before.db"
    await _before_0076(db)
    await _boot(db)
    tables, columns = _shape(db)
    assert "project_habits" not in tables
    assert "habit" not in columns and {"id", "name", "band", "clear_condition", "state"} <= columns
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            assert conn.execute(sa.text("SELECT id, name, band, clear_condition, state FROM project_levels")).all() \
                == [("l1", "Look approved", "shaping", "You approve the key art", "current")]
            assert conn.execute(sa.text("SELECT level_id FROM project_checkpoints")).scalars().all() == ["l1"]
            assert "0076" in runner.current_versions(conn)
            m0076.upgrade_sync(conn)                                 # a second run changes nothing
    finally:
        engine.dispose()
    assert _shape(db) == (tables, columns)


async def test_a_level_can_be_added_after_the_upgrade(tmp_path):
    """The old table had `habit` NOT NULL with no default, and the model no longer writes it."""
    db = tmp_path / "before.db"
    await _before_0076(db)
    await _boot(db)
    engine = build_engine(f"sqlite+aiosqlite:///{db}")
    try:
        async with AsyncSession(engine) as session:
            session.add(ProjectLevel(id="l2", project_id="p1", position=1, name="Build", band="doing"))
            await session.commit()
            assert (await session.get(ProjectLevel, "l2")).state == "todo"
    finally:
        await engine.dispose()


async def test_a_new_install_ends_without_them_and_the_next_launch_does_not_bring_them_back(tmp_path):
    db = tmp_path / "fresh.db"
    for _ in range(2):                                               # the first launch, then the next
        await _boot(db)
        tables, columns = _shape(db)
        assert "project_habits" not in tables and "project_levels" in tables
        assert "habit" not in columns
