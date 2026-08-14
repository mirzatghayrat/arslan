"""Connect an MCP server, discover its tools, naturalize them into Tool/Toolset rows
(locked: tier=orchestrator/status=registered). suggest_tier is a derived UI hint only."""
from __future__ import annotations

import httpx
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


def _describe_failure(exc: BaseException, *, has_headers: bool) -> str:
    """last_error for a failed connect — classified, and never empty.

    Two shapes this replaces. A 401 used to become `str(exc)[:500]`: whatever
    prose httpx chose, with no hint that the fix is credentials rather than the
    server. And `str(InvalidToken())` is the EMPTY STRING (measured, spec ⓪
    §2.3), so the same line could write a blank last_error — an error slot that
    reads as unset.

    The status error may arrive wrapped (anyio task groups), so the walk looks
    inside groups and causes, depth-limited rather than recursion-trusting.
    """
    # An index walk, not `for e in seen[:32]`: that slice is snapshotted before
    # the loop body ever appends, so wrapped exceptions would never be visited —
    # the exact case the walk exists for. (Caught by the wrapped-401 test.)
    seen: list[BaseException] = [exc]
    i = 0
    while i < len(seen) and i < 32:
        e = seen[i]
        i += 1
        if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (401, 403):
            code = e.response.status_code
            if has_headers:
                return (
                    f"authorization failed (HTTP {code}): the server rejected the "
                    "configured headers — re-check the token/key on this server"
                )
            return (
                f"authorization failed (HTTP {code}): no credentials are configured "
                "for this server — it requires authentication"
            )
        seen.extend(getattr(e, "exceptions", ()) or ())
        for link in (e.__cause__, e.__context__):
            if link is not None and link not in seen:
                seen.append(link)
    text = str(exc).strip()
    # An exception whose str() is empty must still leave a trace a human can read.
    return text[:500] if text else f"{type(exc).__name__} (no message)"


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
            srv.last_error = _describe_failure(exc, has_headers=bool(server.get("env")))
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
