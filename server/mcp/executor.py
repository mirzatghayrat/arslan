"""Proxy executor: routes one MCP tool call through the session manager. MCP output is
UNTRUSTED external content → result carries NO external:False, so tool_loop wrap_externals it."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import update

from server.db import session as db_session
from server.db.models import MCPServer, Tool
from server.mcp.session import manager

logger = logging.getLogger(__name__)

_STORED_ERROR_CAP = 500   # chars of upstream error text kept in mcp_servers.last_error


def _summarize_content(content) -> str:
    parts = [t for t in (getattr(b, "text", None) for b in (content or [])) if t]
    return ("\n".join(parts))[:6000] or "(no text content)"


async def _persist_last_error(server_id: int, err: str | None) -> None:
    """Record the latest failure (or clear it on success) in mcp_servers.last_error.
    Fail-open: a persistence problem is logged and never masks the tool result."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            await db.execute(update(MCPServer).where(MCPServer.id == server_id)
                             .values(last_error=err))
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("mcp: could not persist last_error for server %s", server_id,
                       exc_info=True)


class MCPProxyExecutor:
    def __init__(self, server_id: int, external_name: str) -> None:
        self.server_id = server_id
        self.external_name = external_name
        self.key = f"mcp_{server_id}__{external_name}"

    async def _fail(self, err_text: str, prefix: str) -> dict:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        await _persist_last_error(
            self.server_id,
            f"{stamp} call_tool {self.external_name}: {err_text[:_STORED_ERROR_CAP]}")
        # 条件1: the upstream error body is EXTERNAL content. tool_loop's
        # _record_tool_result serializes the WHOLE result dict and wrap_external's it
        # unless external is False — the "error" field gets the exact same framing as
        # "summary" (per-result, not per-field). That granularity means the trusted
        # [MCP label · transport] prefix cannot sit outside the wrapped region, so the
        # entire enriched string lives inside the EXTERNAL_WEB_CONTENT frame. We keep
        # NO external:False here so that framing applies.
        return {"ok": False, "error": prefix + err_text}

    async def execute(self, args: dict) -> dict:
        async with db_session.AsyncSessionLocal() as db:
            srv = await db.get(MCPServer, self.server_id)
        if srv is None:
            return {"ok": False, "error": f"MCP server {self.server_id} not found"}
        from server.mcp.discovery import runtime_dict
        server = runtime_dict(srv)
        prefix = f"[MCP {srv.label} · {server.get('transport') or 'stdio'}] "
        try:
            result = await manager.call_tool(server, self.external_name, args or {})
        except Exception as exc:  # noqa: BLE001
            return await self._fail(f"MCP tool '{self.external_name}' failed: {exc}", prefix)
        text = _summarize_content(getattr(result, "content", None))
        if getattr(result, "isError", False):
            return await self._fail(text, prefix)
        if srv.last_error is not None:            # column reflects the LATEST state
            await _persist_last_error(self.server_id, None)
        return {"ok": True, "summary": text}      # no external:False → wrap_external applies


async def build_mcp_executor(tool_key: str):
    """Resolve an mcp_* Tool key → MCPProxyExecutor, or None if not an MCP tool / not found."""
    async with db_session.AsyncSessionLocal() as db:
        tool = await db.get(Tool, tool_key)
    if tool is None or not (tool.toolset_key or "").startswith("mcp_"):
        return None
    try:
        server_id = int(tool.toolset_key.split("_", 1)[1])
    except (ValueError, IndexError):
        return None
    return MCPProxyExecutor(server_id=server_id, external_name=tool.external_name or "")
