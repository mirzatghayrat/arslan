"""0098 (S5a, v0.1.64): permission modes per conversation; ASK1's "when to ask" setting becomes the default mode.

Two nullable columns on `conversation_contexts` (the per-conversation row): `permission_mode` (plan | ask | ask_risky |
full_access; NULL = the default) and `previous_mode` (what plan's "Start" restores).

The settings key `shell_confirm_policy` is replaced by `default_permission_mode` (the user's decision, 2026-11-14): a
stored `ask_all` exactly (what Settings wrote for "ask every command") becomes `ask`; any other stored value becomes
`ask_risky`; with none stored nothing is written (unset reads `ask_risky`). The old key is deleted, so it isn't kept
in a second place. A `default_permission_mode` already stored is left as it is.

Idempotent (a second run changes nothing); a database without a table is left alone for it (a new install's
create_all makes the columns). Downgrade: older code reads an unset `shell_confirm_policy` as ask_risky, so a user who
had ask_all would read ask_risky after a downgrade; nothing is written back (the column and key are harmless).
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "conversation_contexts" in tables:
        have = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(conversation_contexts)")}
        for column in ("permission_mode", "previous_mode"):
            if column not in have:
                connection.exec_driver_sql(f"ALTER TABLE conversation_contexts ADD COLUMN {column} VARCHAR(20)")
    if "settings" not in tables:
        return
    stored = connection.exec_driver_sql("SELECT value FROM settings WHERE key = 'shell_confirm_policy'").fetchone()
    if stored is not None:
        mode = "ask" if stored[0] == "ask_all" else "ask_risky"
        connection.exec_driver_sql(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('default_permission_mode', ?)", (mode,))
        connection.exec_driver_sql("DELETE FROM settings WHERE key = 'shell_confirm_policy'")


def downgrade_sync(connection) -> None:
    """Nothing to undo (see the docstring)."""
    return
