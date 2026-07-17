"""Inbound-MCP audit skeleton (spec Q3 detail 4).

v1 = one structured log line per inbound MCP request/tool call (tool, status, and an
optional short non-secret detail). It NEVER receives secret material — callers pass
only a tool name and a status. This is the seam v2's ``dispatch_spawn`` audit grows on
(it may be backed by a table later)."""
from __future__ import annotations

import logging

logger = logging.getLogger("arslan.mcp_server.audit")


def record(*, tool: str, status: str, detail: str = "") -> None:
    logger.info("mcp_audit tool=%s status=%s%s", tool, status,
                (" detail=" + detail) if detail else "")
