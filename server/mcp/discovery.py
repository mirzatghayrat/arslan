"""Connect an MCP server, discover its tools, naturalize them into Tool/Toolset rows
(locked: tier=orchestrator/status=registered). suggest_tier is a derived UI hint only."""
from __future__ import annotations

import hashlib
import json

from server.db import session as db_session
from server.db.models import MCPServer, Tool, Toolset
from server.mcp.session import manager

_READ_VERBS = ("list", "get", "search", "read", "fetch", "query", "find", "describe", "show", "view")
_WRITE_VERBS = ("write", "create", "delete", "update", "exec", "run", "send", "patch", "move", "install", "remove", "set")


def suggest_tier(tool_name: str) -> str:
    n = (tool_name or "").lower()
    if any(n.startswith(v) or f"_{v}" in n for v in _WRITE_VERBS):
        return "orchestrator"
    if any(n.startswith(v) or f"_{v}" in n for v in _READ_VERBS):
        return "safe"
    return "orchestrator"           # unknown → conservative



def suggested_tier_for(srv, tool_name: str) -> str:
    """The tier hint for one tool of one server.

    A HAND-GRADED table wins over the heuristic, because the heuristic is a
    verb-list and some servers do not speak in those verbs. Playwright is the
    worked example: not one of snapshot / click / navigate / type appears in
    either list, so every tool — including the purely observational ones —
    comes back "orchestrator", and a toolset with no safe tool cannot be
    assigned to a spawn at all. Grading by hand is not a shortcut around the
    conservative default; it is the only way to distinguish "we looked and this
    one only reads" from "nothing matched a pattern".
    """
    from server.mcp.catalog import manual_tier

    return manual_tier(getattr(srv, "args", None), tool_name) or suggest_tier(tool_name)


def mcp_tool_key(server_id: int, name: str) -> str:
    """Namespaced, length-guarded (Tool.key is VARCHAR(50)). Original name lives in external_name."""
    key = f"mcp_{server_id}__{name}"
    if len(key) <= 50:
        return key
    digest = hashlib.sha1(name.encode()).hexdigest()[:8]
    prefix = f"mcp_{server_id}__"
    return (prefix + name)[: 50 - 9] + "_" + digest     # keep prefix + 8-char hash, fits 50


def runtime_dict(srv) -> dict:
    """Decrypted, transport-aware server dict for the session manager."""

    from server import crypto
    env = {}
    if srv.env:
        try:
            env = json.loads(crypto.decrypt(srv.env))
        except Exception:  # noqa: BLE001
            env = {}
    return {"id": srv.id, "transport": srv.transport or "stdio",
            "command": srv.command, "args": srv.args or [], "url": srv.url, "env": env}


async def connect_and_discover(server_id: int) -> list[dict]:
    """Returns [{key,name,description,suggested_tier}, ...]. Marks server connected/error."""
    async with db_session.AsyncSessionLocal() as db:
        srv = await db.get(MCPServer, server_id)
        if srv is None:
            raise ValueError(f"mcp server {server_id} not found")
        server = runtime_dict(srv)
    try:
        listed = await manager.list_tools(server)
    except Exception as exc:  # noqa: BLE001
        async with db_session.AsyncSessionLocal() as db:
            srv = await db.get(MCPServer, server_id)
            srv.status = "error"
            srv.last_error = str(exc)[:500]
            await db.commit()
        raise
    discovered: list[dict] = []
    async with db_session.AsyncSessionLocal() as db:
        ts_key = f"mcp_{server_id}"
        srv = await db.get(MCPServer, server_id)
        ts = await db.get(Toolset, ts_key)
        if ts is None:
            ts = Toolset(key=ts_key, name=srv.label, description=f"MCP server: {srv.command}",
                         tier="orchestrator", status="registered", backend_note=f"MCP: {srv.command}")
            db.add(ts)
        for t in listed.tools:
            key = mcp_tool_key(server_id, t.name)
            schema = getattr(t, "inputSchema", None) or {}
            existing = await db.get(Tool, key)
            if existing is None:
                db.add(Tool(key=key, toolset_key=ts_key, description=t.description or t.name,
                            tier="orchestrator", status="registered", input_schema=schema,
                            external_name=t.name))
            else:
                existing.description = t.description or t.name
                existing.input_schema = schema
                existing.external_name = t.name
            discovered.append({"key": key, "name": t.name, "description": t.description or "",
                               "suggested_tier": suggested_tier_for(srv, t.name)})
        srv.status = "connected"
        srv.last_error = None
        await db.commit()
    return discovered
