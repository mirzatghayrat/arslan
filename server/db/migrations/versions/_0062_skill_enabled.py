"""0062: a skill can be switched off without deleting it (0.1.55 §14).

`skill_packs.enabled` defaults to 1, so every existing skill stays offered exactly as
before. Off = the skill is left out of the index the model sees and read_skill refuses
it. Idempotent; fresh databases get the column from Base.metadata.create_all.
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(skill_packs)")}
    if "enabled" not in columns:
        connection.exec_driver_sql("ALTER TABLE skill_packs ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT 1")


def downgrade_sync(connection) -> None:
    connection.exec_driver_sql("ALTER TABLE skill_packs DROP COLUMN enabled")
