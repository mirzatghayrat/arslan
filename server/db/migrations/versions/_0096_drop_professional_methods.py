"""0096 (v0.1.64 SUB6b): the professional methods' tables go.

SUB6b deleted the three professional methods (research, apple-growth, product-design), their editor, their
routes and their two models; nothing reads or writes `professional_methods` or `professional_method_versions`
any more. The versions table refers to the methods table, so it is dropped first. The methods' rows (the
defaults and any revisions the user saved) are in the upgrade backup the runner takes before this migration
(`prepare_upgrade_backup`) until that backup is pruned.

0052 still creates both tables, empty, on a new install (from its own definitions, not the deleted models);
this then drops them. Idempotent: a database without the tables (a second run) is left alone.
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS professional_method_versions")
    connection.exec_driver_sql("DROP TABLE IF EXISTS professional_methods")


def downgrade_sync(connection) -> None:
    """Nothing to restore: no code reads the tables, and their rows are in the upgrade backup while it is kept."""
    return
