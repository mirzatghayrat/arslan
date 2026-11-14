"""0095 (ASK1-a, v0.1.64): "ask only for risky commands" is the default again, and existing installs are told once.

An unset shell_confirm_policy now reads as ask_risky (settings_service.shell_confirm_policy); a stored ask_all and
any other spelling still read as ask_all. This migration writes nothing to the policy. It only sets the one-time
note, `shell_policy_switch_notice = pending`, on an install that existed before this boot
(runner.EXISTED_BEFORE_THIS_BOOT, read as 0070 reads it; called on its own, an install counts as existing) whose
stored policy is not exactly ask_risky: an unset policy (which now reads ask_risky) and a stored ask_all (which
stays) are both told how to switch, and the window picks the note's text from what the policy reads. It is the key
0070 used, so a 0070 notice still pending is replaced, not shown twice. An install that stores ask_risky (chosen
again after 0070) sees no change: a pending 0070 notice is cleared and none is set. A new install gets none.

Idempotent (a second run leaves the same rows); a database without the settings table is left alone. Numbered 0095,
not ASK1's reserved 0087: 0089-0092 merged first, and the chain's head is its last entry (docs/sessions.md §4).
The note goes in v0.1.65 (ShellPolicySwitchNotice); this file stays in the chain.
"""
from __future__ import annotations

#: runner.EXISTED_BEFORE_THIS_BOOT (the runner imports this module, so the name is repeated, not imported).
_EXISTED = "database_existed_before_this_boot"


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "settings" not in tables:
        return
    stored = connection.exec_driver_sql(
        "SELECT value FROM settings WHERE key = 'shell_confirm_policy'").scalar()
    if stored == "ask_risky":                      # the reader's exact value: nothing changes for this install
        connection.exec_driver_sql(
            "DELETE FROM settings WHERE key = 'shell_policy_switch_notice' AND value = 'pending'")
    elif connection.info.get(_EXISTED, True):
        connection.exec_driver_sql(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('shell_policy_switch_notice', 'pending')")

def downgrade_sync(connection) -> None:
    """Nothing to undo: the note's key is one every version since v0.1.63 reads."""
    return
