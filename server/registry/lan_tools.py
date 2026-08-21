"""The LAN discovery tool (spec P3a).

Read-only: it observes which machines are on the user's own network and what
kind they look like. It never connects to a service, authenticates, or runs
anything — reaching a machine is P3b, behind its own gate.

The setting is checked HERE as well as at registration. A tool list can be
stale within a long turn, and a direct call bypasses registration entirely;
neither should be able to scan a network the user never opted into.
"""
from __future__ import annotations

from server.db import session as db_session
from server.services import lan_scan, settings_service


class ScanLocalNetworkExecutor:
    key = "scan_local_network"

    async def execute(self, args: dict) -> dict:
        async with db_session.AsyncSessionLocal() as db:
            if not await settings_service.lan_discovery_enabled(db):
                return {"ok": False,
                        "error": "local network discovery is off — the user can turn "
                                 "it on in Settings"}
        return await lan_scan.scan()
