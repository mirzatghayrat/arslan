"""CRUD + connect/expose/wire for MCP servers. env stored encrypted, masked on read."""
from __future__ import annotations

import json

from sqlalchemy import select

from server import crypto
from server.db import session as db_session
from server.db.models import MCPServer, Tool, Toolset
from server.mcp import discovery
from server.services.settings_service import mask_secret


def _mask_env(env: dict) -> dict:
    return {k: mask_secret(v) for k, v in (env or {}).items()}


def _to_dict(srv: MCPServer, *, mask: bool = True) -> dict:
    env = {}
    if srv.env:
        try:
            env = json.loads(crypto.decrypt(srv.env))
        except Exception:  # noqa: BLE001
            env = {}
    return {"id": srv.id, "label": srv.label, "command": srv.command, "args": srv.args or [],
            "url": srv.url, "env": _mask_env(env) if mask else env, "status": srv.status,
            "last_error": srv.last_error, "transport": srv.transport}


async def add_server(label: str, command: str, args: list[str], env: dict,
                     transport: str = "stdio", url: str | None = None) -> dict:
    async with db_session.AsyncSessionLocal() as db:
        srv = MCPServer(label=label, command=command or "", args=args or [], transport=transport, url=url,
                        env=crypto.encrypt(json.dumps(env or {})), status="registered")
        db.add(srv)
        await db.commit()
        await db.refresh(srv)
        return _to_dict(srv)


async def list_servers() -> list[dict]:
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(MCPServer).order_by(MCPServer.id))).scalars().all()
        return [_to_dict(s) for s in rows]


async def connect(server_id: int) -> list[dict]:
    return await discovery.connect_and_discover(server_id)


async def list_tools(server_id: int) -> list[dict]:
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Tool).where(Tool.toolset_key == f"mcp_{server_id}").order_by(Tool.key)
        )).scalars().all()
        return [{"key": t.key, "name": t.external_name or t.key, "description": t.description,
                 "tier": t.tier, "status": t.status, "host_enabled": t.host_enabled,
                 "suggested_tier": discovery.suggest_tier(t.external_name or "")}
                for t in rows]


async def set_exposed(server_id: int, exposed: bool) -> None:
    async with db_session.AsyncSessionLocal() as db:
        ts = await db.get(Toolset, f"mcp_{server_id}")
        if ts is None:
            return
        ts.tier = "safe" if exposed else "orchestrator"
        ts.status = "registered"
        await db.commit()


async def wire_tool(tool_key: str, tier: str, wired: bool) -> None:
    if tier not in ("safe", "orchestrator"):
        raise ValueError("tier must be safe|orchestrator")
    async with db_session.AsyncSessionLocal() as db:
        tool = await db.get(Tool, tool_key)
        if tool is None or not (tool.toolset_key or "").startswith("mcp_"):
            raise ValueError("not an MCP tool")
        tool.tier = tier
        tool.status = "wired" if wired else "registered"
        await db.commit()


async def set_host_enabled(tool_key: str, enabled: bool) -> None:
    async with db_session.AsyncSessionLocal() as db:
        tool = await db.get(Tool, tool_key)
        if tool is None or not (tool.toolset_key or "").startswith("mcp_"):
            raise ValueError("not an MCP tool")
        tool.host_enabled = enabled
        await db.commit()


async def reconnect(server_id: int) -> None:
    from server.mcp.session import manager
    await manager._drop(server_id)


async def delete_server(server_id: int) -> None:
    from server.mcp.session import manager
    await manager._drop(server_id)
    async with db_session.AsyncSessionLocal() as db:
        for t in (await db.execute(select(Tool).where(Tool.toolset_key == f"mcp_{server_id}"))).scalars().all():
            await db.delete(t)
        ts = await db.get(Toolset, f"mcp_{server_id}")
        if ts is not None:
            await db.delete(ts)
        srv = await db.get(MCPServer, server_id)
        if srv is not None:
            await db.delete(srv)
        await db.commit()
