"""Proxy executor: routes one MCP tool call through the session manager. MCP output is
UNTRUSTED external content → result carries NO external:False, so tool_loop wrap_externals it."""
from __future__ import annotations

from server.db import session as db_session
from server.db.models import MCPServer, Tool
from server.mcp.session import manager


def _summarize_content(content) -> str:
    parts = [t for t in (getattr(b, "text", None) for b in (content or [])) if t]
    return ("\n".join(parts))[:6000] or "(no text content)"


class MCPProxyExecutor:
    def __init__(self, server_id: int, external_name: str) -> None:
        self.server_id = server_id
        self.external_name = external_name
        self.key = f"mcp_{server_id}__{external_name}"

    async def execute(self, args: dict) -> dict:
        async with db_session.AsyncSessionLocal() as db:
            srv = await db.get(MCPServer, self.server_id)
        if srv is None:
            return {"ok": False, "error": f"MCP server {self.server_id} not found"}
        from server import crypto
        import json
        env = {}
        if srv.env:
            try:
                env = json.loads(crypto.decrypt(srv.env))
            except Exception:  # noqa: BLE001
                env = {}
        server = {"id": srv.id, "command": srv.command, "args": srv.args or [], "env": env}
        try:
            result = await manager.call_tool(server, self.external_name, args or {})
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"MCP tool '{self.external_name}' failed: {exc}"}
        text = _summarize_content(getattr(result, "content", None))
        if getattr(result, "isError", False):
            return {"ok": False, "error": text}
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
