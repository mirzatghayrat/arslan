"""0063: projects in two layers (0.1.56).

Adds nullable columns to `projects` (template, finish_line, stage, paused, done_at,
plan_version) — no CHECK change, so no table rebuild — and four tables: the plan's
levels and checkpoints, the event log (ticks, proposals with their outcome, advances,
plan and stage changes), and the user's project habits. None of this touches
`projects.version`, which pins running tasks. Idempotent; fresh databases get the same
shape from Base.metadata.create_all.
"""
from __future__ import annotations

_COLUMNS = (
    ("template", "VARCHAR(30)"),
    ("finish_line", "TEXT"),
    ("stage", "VARCHAR(20)"),
    ("paused", "BOOLEAN"),
    ("done_at", "DATETIME"),
    ("plan_version", "INTEGER"),
)

_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS project_levels (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        project_id VARCHAR(36) NOT NULL REFERENCES projects (id),
        position INTEGER NOT NULL,
        name VARCHAR(120) NOT NULL,
        description VARCHAR(300) NOT NULL DEFAULT '',
        band VARCHAR(10) NOT NULL,
        clear_condition VARCHAR(400) NOT NULL DEFAULT '',
        state VARCHAR(10) NOT NULL DEFAULT 'todo',
        habit BOOLEAN NOT NULL DEFAULT 0,
        started_at DATETIME,
        cleared_at DATETIME,
        CONSTRAINT ck_project_level_band CHECK (band IN ('shaping','doing','done')),
        CONSTRAINT ck_project_level_state CHECK (state IN ('todo','current','cleared'))
    )""",
    "CREATE INDEX IF NOT EXISTS ix_project_levels_project_id ON project_levels (project_id)",
    """CREATE TABLE IF NOT EXISTS project_checkpoints (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        level_id VARCHAR(36) NOT NULL REFERENCES project_levels (id),
        position INTEGER NOT NULL,
        text VARCHAR(200) NOT NULL,
        expects JSON,
        state VARCHAR(10) NOT NULL DEFAULT 'todo',
        progress VARCHAR(40),
        evidence JSON,
        done_at DATETIME,
        done_by VARCHAR(10),
        CONSTRAINT ck_project_checkpoint_state CHECK (state IN ('todo','done'))
    )""",
    "CREATE INDEX IF NOT EXISTS ix_project_checkpoints_level_id ON project_checkpoints (level_id)",
    """CREATE TABLE IF NOT EXISTS project_events (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        project_id VARCHAR(36) NOT NULL REFERENCES projects (id),
        kind VARCHAR(20) NOT NULL,
        actor VARCHAR(10) NOT NULL,
        payload JSON NOT NULL,
        outcome VARCHAR(10),
        undo_of VARCHAR(36),
        created_at DATETIME NOT NULL,
        CONSTRAINT ck_project_event_kind CHECK (kind IN ('tick','untick','proposal','advance','plan_change','plan_proposal','stage','activity','handoff','retro')),
        CONSTRAINT ck_project_event_actor CHECK (actor IN ('user','arslan'))
    )""",
    "CREATE INDEX IF NOT EXISTS ix_project_events_project_id ON project_events (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_project_events_created_at ON project_events (created_at)",
    """CREATE TABLE IF NOT EXISTS project_habits (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        owner_id VARCHAR(100) NOT NULL DEFAULT 'local',
        template VARCHAR(30),
        kind VARCHAR(20) NOT NULL,
        text VARCHAR(300) NOT NULL,
        value JSON,
        sources JSON NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT 1,
        created_at DATETIME NOT NULL,
        CONSTRAINT ck_project_habit_kind CHECK (kind IN ('plan_rule','pace_override'))
    )""",
)


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    if "projects" in tables:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(projects)")}
        for name, kind in _COLUMNS:
            if name not in columns:
                connection.exec_driver_sql(f"ALTER TABLE projects ADD COLUMN {name} {kind}")
        for statement in _STATEMENTS:
            connection.exec_driver_sql(statement)


def downgrade_sync(connection) -> None:
    for table in ("project_checkpoints", "project_levels", "project_events", "project_habits"):
        connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
