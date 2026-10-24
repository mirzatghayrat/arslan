"""0070: "ask before every command" becomes the default, for everyone once (v0.1.63, user's decision).

Until now an unset policy read as "ask only for risky commands" (ask_risky, the default since 0.1.48), whose
judgement of what is risky has known gaps that v0.1.64 closes (S2a-3). Unset now reads as ask_all
(settings_service.shell_confirm_policy), and a stored ask_risky moves to ask_all here. It is not taken as a
choice: the store keeps the value, not whether or when it was chosen. The composer's one-click toggle before
0.1.48, a local tool that writes settings, or a restored backup can each leave it with nobody having chosen it
(⓪Plan and the cloud audit: when a choice cannot be told from a value written for the user, switch).

A choice made after this runs is kept: the runner records 0070 and never runs it again, and only the user's own
actions write the key. Idempotent (a second run finds nothing to move); a database without the table is left
alone. It matches exactly what the reader counts as ask_risky (settings_service.shell_confirm_policy: the exact
value, what Settings writes); any other spelling already reads as ask_all.

When it moves a stored value it also leaves `shell_policy_switch_notice = pending`: the window tells that user once
that they were switched, how to switch back, and the known issue (R63, the user's decision on 10-24). Nobody it did
not move gets the notice. DELETE-BY: v0.1.64, with the notice (once S2a-3 lands its text is no longer true).
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "settings" in tables:
        moved = connection.exec_driver_sql(
            "UPDATE settings SET value = 'ask_all'"
            " WHERE key = 'shell_confirm_policy' AND value = 'ask_risky'").rowcount
        if moved:
            connection.exec_driver_sql(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('shell_policy_switch_notice', 'pending')")


def downgrade_sync(connection) -> None:
    """Nothing to undo: ask_all is a value every version reads."""
    return
