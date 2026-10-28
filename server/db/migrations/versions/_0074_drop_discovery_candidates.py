"""0074: drop `discovery_candidates`, the discovery centre's saved catalog (v0.1.64 CAP1b).

CAP1a removed every reader and writer (the Discover tab's "Saved" list and its routes). The rows were
snapshots of GitHub repositories the user looked at, not the user's skills or connections, so nothing
is carried over. Its own PR after the code, so reverting CAP1a never needs the table back (plan §6).

Idempotent: a database without the table (a second run, or an install that never had it) is left alone.
0012 still creates the table on a new install; this then drops it.
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS discovery_candidates")


def downgrade_sync(connection) -> None:
    """Nothing to restore: the catalog's rows are gone, and no code reads the table."""
    return
