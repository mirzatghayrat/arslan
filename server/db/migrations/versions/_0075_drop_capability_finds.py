"""0075: drop `capability_finds`, what the "found for later" rail showed (v0.1.64 CAP1c).

CAP1a removed every reader and writer: with nobody to ask, a missing capability is now named in the
model's answer instead (the CAP card, open question 2). The rows were search
results kept for later, not the user's skills or connections, so nothing is carried over; they stay in
the upgrade backup the runner takes before any migration (`prepare_upgrade_backup`). Its own PR
after the code, so reverting CAP1a never needs the table back (plan §6). `capability_sources`, which
0064 created beside it, stays: the installed capabilities' dossiers read it.

Idempotent: a database without the table (a second run, or an install that never had it) is left alone.
0064 still creates the table and its index on a new install; this then drops both.
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    connection.exec_driver_sql("DROP INDEX IF EXISTS ix_capability_finds_created_at")
    connection.exec_driver_sql("DROP TABLE IF EXISTS capability_finds")


def downgrade_sync(connection) -> None:
    """Nothing to restore: no code reads the table, and its rows are in the upgrade backup."""
    return
