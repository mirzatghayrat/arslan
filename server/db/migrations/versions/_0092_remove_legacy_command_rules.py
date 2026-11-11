"""0092: deletes the old "don't ask again" command rules and the grants no request reads (v0.1.64, S6, data only).

Since S2a-2 no decision reads a `legacy_rule` row (a command's rule card is this time only), so the rows 0067
copied from the 0.1.48 list decide nothing. The user chose on 2026-11-11 that they are deleted, not listed: this
removes every `permission_rules` row of kind `legacy_rule`, and the `terminal_always_allow` settings row they were
copied from (0067 kept it for a downgrade; a 0.1.60 build reading it would bring them back). Nothing writes either
again: the Inbox's "Always allow" refuses a recorded set that names one (`permissions.always_from`), and no card may
store one (`permissions._check`).

After #836's review the user chose the same for the grants no request reads (dead grants): every `permission_grants`
row whose (kind, target) no current request can match. That is a 0.1.61–0.1.62 rule card's `command` / `rules:<rules>`
(and any `command` target but `text:<command>` and `unsandboxed:*`), a grant of a once-only kind, of a kind no request
is granted for (`destructive`, `folder`, `send`, `screen`) or of a kind outside the permission kinds, and an
`outside`, `network` or `schedule` grant under another target than the one its request uses. The rule is a frozen
copy of `permissions.grant_is_live` as of v0.1.64 (constants below, nothing imported from the app): history stays
what it was when the app's rule changes, and a test fails loudly when the two disagree.

Every live grant is left exactly as it was, as are other rules and the ledger. A re-run finds nothing more to do.
Runs in the boot transaction, after the upgrade backup.
"""
from __future__ import annotations

#: Frozen copy of `permissions._LIVE_GRANT_TARGETS` (v0.1.64): per kind, how a target a request reads looks —
#: ("exact", value), ("prefix", value), or ("any", "") for any non-empty target. A kind not here is dead.
_LIVE_GRANT_TARGETS: dict[str, tuple[tuple[str, str], ...]] = {
    "command": (("exact", "unsandboxed:*"), ("prefix", "text:")),
    "outside": (("exact", "*"),),
    "network": (("exact", "network:*"),),
    "schedule": (("exact", "*"),),
    "workspace_write": (("any", ""),),
    "mcp_tool": (("prefix", "mcp_"),),
    "app": (("any", ""),),
    "site": (("any", ""),),
    "shortcut": (("any", ""),),
}


def _grant_is_live(kind: str, target: str) -> bool:
    target = target or ""
    for how, value in _LIVE_GRANT_TARGETS.get(kind, ()):
        if (how == "exact" and target == value) or (how == "prefix" and target.startswith(value)) \
                or (how == "any" and target):
            return True
    return False


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('permission_rules', 'permission_grants', 'settings')").fetchall()}
    if "permission_rules" in tables:
        connection.exec_driver_sql("DELETE FROM permission_rules WHERE kind = 'legacy_rule'")
    if "settings" in tables:
        connection.exec_driver_sql("DELETE FROM settings WHERE key = 'terminal_always_allow'")
    if "permission_grants" in tables:
        dead = [row_id for row_id, kind, target in connection.exec_driver_sql(
            "SELECT id, kind, target FROM permission_grants").fetchall() if not _grant_is_live(kind, target)]
        for row_id in dead:
            connection.exec_driver_sql("DELETE FROM permission_grants WHERE id = ?", (row_id,))


def downgrade_sync(connection) -> None:
    """No-op: an older build reads no rows as no rules or grants, and asks."""
    return
