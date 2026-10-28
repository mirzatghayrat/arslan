"""0072: `runs.read_outside`, whether a run read outside content (v0.1.64, INB2).

Each run's turns record whether they read outside content (web pages, files, MCP output, a helper's or a
job's report, an attachment: server/orchestrator/untrusted.py). INB2 lets an "about you" memory take effect
directly only when every run of the conversation says it read none. A run with no record, NULL here, counts
as having read some: every run from before this migration, a run that crashed before its turn ended, and a
job still running. So nothing old ever qualifies, and nothing has to be written the moment the mark changes.

Adds the column only (no backfill: NULL is the answer for old runs). Idempotent; a database without `runs`
is left alone.
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "runs" not in tables:
        return
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(runs)").fetchall()}
    if "read_outside" not in columns:
        connection.exec_driver_sql("ALTER TABLE runs ADD COLUMN read_outside BOOLEAN")


def downgrade_sync(connection) -> None:
    """Nothing to undo: an older version ignores the column."""
    return
