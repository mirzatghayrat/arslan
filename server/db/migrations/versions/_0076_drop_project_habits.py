"""0076: drop `project_habits` and `project_levels.habit` (v0.1.64 PRJ0's table drop).

PRJ0 removed every reader and writer: "learn how you advance gates" (plan rules and pace
overrides) is gone and nothing replaces it (the SUB card: the table had 0 rows on the user's
machine). The rows stay in the upgrade backup the runner takes before any migration
(`prepare_upgrade_backup`). Its own PR after the code, so reverting PRJ0 never needs the table back.

The column goes with the model's: a database that create_all made from the old model has `habit`
NOT NULL with no default in the table, so adding a level would fail once the model stops writing it.

Idempotent: a database without the table or the column (a second run, or a new install) is left
alone. 0063 still creates the table on a new install; this then drops it.
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS project_habits")
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(project_levels)")}
    if "habit" in columns:
        connection.exec_driver_sql("ALTER TABLE project_levels DROP COLUMN habit")


def downgrade_sync(connection) -> None:
    """Nothing to restore: no code reads either, and the rows are in the upgrade backup."""
    return
