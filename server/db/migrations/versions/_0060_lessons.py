"""0060: learned practices — lessons v1 (0.1.52 S5).

One row per practice Arslan learned: "in this situation → do / avoid this", where it
came from (the user's correction, a detour that ended in success, a quirk of this
Mac), its evidence, its status (active | proposed | stale | archived), whether the
user pinned it, and the counters the P4b curator will use (recalled, followed,
succeeded, failed). Idempotent; fresh databases get the same shape from
Base.metadata.create_all.
"""
from __future__ import annotations

_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS lessons (
        id INTEGER NOT NULL PRIMARY KEY,
        owner_id VARCHAR(100) NOT NULL DEFAULT 'local',
        situation VARCHAR(300) NOT NULL,
        advice VARCHAR(400) NOT NULL,
        polarity VARCHAR(10) NOT NULL,
        source VARCHAR(20) NOT NULL,
        evidence JSON,
        status VARCHAR(10) NOT NULL,
        pinned BOOLEAN NOT NULL DEFAULT 0,
        recalled INTEGER NOT NULL DEFAULT 0,
        followed INTEGER NOT NULL DEFAULT 0,
        succeeded INTEGER NOT NULL DEFAULT 0,
        failed INTEGER NOT NULL DEFAULT 0,
        last_used_at DATETIME,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        CONSTRAINT ck_lesson_polarity CHECK (polarity IN ('do', 'avoid')),
        CONSTRAINT ck_lesson_source CHECK (source IN ('user_correction', 'detour', 'machine_quirk')),
        CONSTRAINT ck_lesson_status CHECK (status IN ('active', 'proposed', 'stale', 'archived'))
    )""",
    "CREATE INDEX IF NOT EXISTS ix_lessons_status ON lessons (status)",
)


def upgrade_sync(connection) -> None:
    for statement in _STATEMENTS:
        connection.exec_driver_sql(statement)


def downgrade_sync(connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS lessons")
