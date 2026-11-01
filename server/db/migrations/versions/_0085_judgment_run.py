"""0085: `judgments.run_id`, the run a judgment belongs to (v0.1.64, for INB7-c4b).

Progress shows a run's judgments with that run. Matching them by conversation and time went wrong for the after-turn
job's memory questions, which come after the run has ended, for two runs close together, and for a background job's
job.accomplished. `judgment.judge` writes the id; rows from before stay null, and Progress matches those by time.

Add-only: one nullable column, no data moved, so reverting the code that uses it needs nothing back. Idempotent: a column
already there is left alone, and so is a database without the table (a new install's create_all makes it with the column).
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "judgments" not in tables:
        return
    have = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(judgments)")}
    if "run_id" not in have:
        connection.exec_driver_sql("ALTER TABLE judgments ADD COLUMN run_id INTEGER")


def downgrade_sync(connection) -> None:
    """Leaving the column is harmless (unread by older code); SQLite before 3.35 cannot drop it."""
    return
