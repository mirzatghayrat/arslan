"""0092: deletes the old "don't ask again" command rules (v0.1.64, S6, data only).

Since S2a-2 no decision reads a `legacy_rule` row (a command's rule card is this time only), so the rows 0067
copied from the 0.1.48 list decide nothing. The user chose on 2026-11-11 that they are deleted, not listed: this
removes every `permission_rules` row of kind `legacy_rule`, and the `terminal_always_allow` settings row they were
copied from (0067 kept it for a downgrade; a 0.1.60 build reading it would bring them back). Nothing else is
touched: other rules, grants and the ledger stay. Nothing writes either again: the Inbox's "Always allow" refuses a
recorded set that names one (`permissions.always_from`), and no card may store one (`permissions._check`). A re-run
finds nothing more to do. Runs in the boot transaction, after the upgrade backup.
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('permission_rules', 'settings')").fetchall()}
    if "permission_rules" in tables:
        connection.exec_driver_sql("DELETE FROM permission_rules WHERE kind = 'legacy_rule'")
    if "settings" in tables:
        connection.exec_driver_sql("DELETE FROM settings WHERE key = 'terminal_always_allow'")


def downgrade_sync(connection) -> None:
    """No-op: an older build reads no rows as no rules, and asks."""
    return
