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

It also leaves `shell_policy_switch_notice = pending` for every existing install that v0.1.62 read as ask_risky,
whether the value was stored or not: the window tells them once that they were switched, how to switch back, and
the known issue (R63, the user's decision on 10-24: "in practice, every old user"). v0.1.62 read everything but
ask_all, in any case and spacing, as ask_risky, its default, so an install that never touched the setting was on
it too. A new install gets no notice: it was never on ask_risky. The runner says which this is
(runner.EXISTED_BEFORE_THIS_BOOT, taken before create_all); called on its own, an install counts as existing.
DELETE-BY: v0.1.64, with the notice, when S2a-3 and #406 land (then its text is no longer true).
"""
from __future__ import annotations

#: runner.EXISTED_BEFORE_THIS_BOOT (the runner imports this module, so the name is repeated, not imported).
_EXISTED = "database_existed_before_this_boot"


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "settings" not in tables:
        return
    before = connection.exec_driver_sql(
        "SELECT value FROM settings WHERE key = 'shell_confirm_policy'").scalar()
    connection.exec_driver_sql(
        "UPDATE settings SET value = 'ask_all'"
        " WHERE key = 'shell_confirm_policy' AND value = 'ask_risky'")
    was_ask_risky = str(before).strip().lower() != "ask_all"      # v0.1.62's reader, word for word
    if was_ask_risky and connection.info.get(_EXISTED, True):
        connection.exec_driver_sql(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('shell_policy_switch_notice', 'pending')")


def downgrade_sync(connection) -> None:
    """Nothing to undo: ask_all is a value every version reads."""
    return
