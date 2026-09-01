"""0044: repair the databases where 0043 recorded success without doing anything.

0043 named the table ``provider_config``; it is ``provider_configs``. Its
first line therefore read "that table does not exist here" and returned, and
apply_pending wrote 0043 into schema_version anyway. A no-op that records
itself as applied is indistinguishable from a real one, so every upgraded
install now claims to have a ``last_health_detail`` column it does not have,
and the ORM selects that column on every provider query — HTTP 500 on the
whole Models screen.

Fixing 0043 in place is not enough: the databases that already recorded it
will never run it again. This migration does the same work under the right
name, and is idempotent, so it is a no-op wherever the fixed 0043 already
landed.

A fresh install was never affected — create_all builds the table from the
current model, so no migration is involved. Only an upgrade could see it, and
nothing in the pipeline upgrades a database.
"""
from __future__ import annotations


def _columns(connection, table: str) -> set[str]:
    return {r[1] for r in connection.exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade_sync(connection) -> None:
    tables = {r[0] for r in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "provider_configs" not in tables:
        return
    if "last_health_detail" not in _columns(connection, "provider_configs"):
        connection.exec_driver_sql(
            "ALTER TABLE provider_configs ADD COLUMN last_health_detail TEXT")
    # The old vocabulary answered a question this column no longer asks, so the
    # rows are cleared rather than translated. NULL reads as "never tested" and
    # the launch sweep refills it with a verdict that means something.
    connection.exec_driver_sql(
        "UPDATE provider_configs SET last_health = NULL, last_health_at = NULL "
        "WHERE last_health IN ('reachable_models','reachable_no_list','unreachable')")
