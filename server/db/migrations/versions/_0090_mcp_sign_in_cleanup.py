"""0090: removes stored MCP sign-ins whose server no longer exists (v0.1.64, data only).

Removing a server now removes its stored sign-in (`mcp_service.delete_server`). This clears what earlier versions left
in `settings`: `mcp_oauth_tokens_<id>` and `mcp_oauth_client_<id>` with no `mcp_servers` row of that id. A server that
exists keeps its own. Any other key is left alone, and a re-run finds nothing more to do. Runs in the boot transaction,
after the upgrade backup.
"""
from __future__ import annotations

import re

_KEY = re.compile(r"mcp_oauth_(?:tokens|client)_(\d+)")


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('settings', 'mcp_servers')").fetchall()}
    if tables != {"settings", "mcp_servers"}:
        return                                                    # nothing stored yet: create_all makes them
    servers = {row[0] for row in connection.exec_driver_sql("SELECT id FROM mcp_servers").fetchall()}
    for (key,) in connection.exec_driver_sql("SELECT key FROM settings WHERE key LIKE 'mcp_oauth_%'").fetchall():
        match = _KEY.fullmatch(key)
        if match and int(match.group(1)) not in servers:
            connection.exec_driver_sql("DELETE FROM settings WHERE key = ?", (key,))


def downgrade_sync(connection) -> None:
    """No-op: older code reads a missing sign-in as none, and the user signs in again."""
    return
