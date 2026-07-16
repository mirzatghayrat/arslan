"""CRUD + connect/expose/wire + health probe for MCP servers. env stored encrypted, masked on read."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from server import crypto
from server.db import session as db_session
from server.db.models import MCPServer, Tool, Toolset
from server.mcp import discovery
from server.services.settings_service import mask_secret

logger = logging.getLogger(__name__)

_HEALTH_PROBE_TIMEOUT = 10.0   # 条件3: the probe is bounded — it must never become a hang point
_STORED_ERROR_CAP = 500        # matches executor._STORED_ERROR_CAP (PB-2 shape)


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
            "last_error": srv.last_error, "transport": srv.transport,
            "health_status": srv.health_status,
            "last_checked_at": srv.last_checked_at.isoformat() if srv.last_checked_at else None}


async def add_server(label: str, command: str, args: list[str], env: dict,
                     transport: str = "stdio", url: str | None = None) -> dict:
    if transport not in ("stdio", "http"):
        raise ValueError("transport must be stdio|http")
    if transport == "http" and not (url or "").strip():
        raise ValueError("http transport requires a url")
    if transport == "stdio" and not (command or "").strip():
        raise ValueError("stdio transport requires a command")
    async with db_session.AsyncSessionLocal() as db:
        # Dedup guard: return existing row if (label, url) or (label, command, args) already present
        existing = None
        if transport == "http":
            result = await db.execute(
                select(MCPServer).where(MCPServer.label == label, MCPServer.url == url)
            )
            existing = result.scalars().first()
        else:
            canon_args = json.dumps(sorted(args or []))
            all_stdio = (await db.execute(
                select(MCPServer).where(MCPServer.label == label, MCPServer.command == (command or ""))
            )).scalars().all()
            for row in all_stdio:
                if json.dumps(sorted(row.args or [])) == canon_args:
                    existing = row
                    break
        if existing is not None:
            return _to_dict(existing)
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


async def tier_counts(server_id: int) -> dict:
    """DB-authoritative tier split for the connect-card follow-up (conversation-driven
    MCP Task 3): {tool_count, safe_count, restricted_count, assignable}. Never trusts a
    frontend-supplied count — always recomputed from the mcp_<id> Toolset's Tool rows.

    `assignable = safe_count >= 1` replicates registry.service.assert_assignable's
    per-toolset `has_wired` gate (server/registry/service.py:377-384: `Tool.tier ==
    "safe", Tool.status == "wired"`) rather than reusing is_assignable(), because that
    helper's status set also admits "registered" — a safe-but-not-yet-wired tool would
    then count as ready when Layer 3 still cannot resolve it. Replicated deliberately so
    the two predicates cannot silently drift: any future edit to the wired-gate in
    assert_assignable should update this comment/predicate pair too."""
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Tool).where(Tool.toolset_key == f"mcp_{server_id}")
        )).scalars().all()
    safe_count = sum(1 for t in rows if t.tier == "safe" and t.status == "wired")
    tool_count = len(rows)
    return {"tool_count": tool_count, "safe_count": safe_count,
            "restricted_count": tool_count - safe_count, "assignable": safe_count >= 1}


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


async def check_health(server_id: int) -> dict:
    """PB-4 on-demand equipment health probe: list_tools with a hard 10s bound.

    Writes health_status ("ok"|"failing") + last_checked_at; failures also land in
    last_error (PB-2 shape: timestamp + context + upstream text). Zero side effects on
    the server's tools — v1 never test-calls anything.
    """
    from server.mcp.discovery import runtime_dict
    from server.mcp.session import manager

    async with db_session.AsyncSessionLocal() as db:
        srv = await db.get(MCPServer, server_id)
        if srv is None:
            raise ValueError(f"mcp server {server_id} not found")
        server = runtime_dict(srv)
        label, transport = srv.label, (srv.transport or "stdio")

    tool_count: int | None = None
    err_text: str | None = None
    try:
        listed = await asyncio.wait_for(manager.list_tools(server), timeout=_HEALTH_PROBE_TIMEOUT)
        tool_count = len(listed.tools)
        health = "ok"
    except TimeoutError:
        # wait_for cancels the probe with CancelledError (BaseException), which
        # list_tools' `except Exception` does NOT catch — drop the cached session
        # explicitly so a wedged subprocess can't poison later calls.
        await manager._drop(server_id)
        health = "failing"
        err_text = f"health probe timed out after {_HEALTH_PROBE_TIMEOUT:g}s"
    except Exception as exc:  # noqa: BLE001 — any probe failure = failing, never a 500
        health = "failing"
        err_text = str(exc)[:_STORED_ERROR_CAP]

    now = datetime.now(timezone.utc).replace(tzinfo=None)   # naive UTC, matches DateTime columns
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    async with db_session.AsyncSessionLocal() as db:
        srv = await db.get(MCPServer, server_id)
        if srv is not None:
            srv.health_status = health
            srv.last_checked_at = now
            if err_text is not None:
                srv.last_error = f"{stamp} health probe list_tools: {err_text}"   # PB-2 shape
            elif srv.last_error is not None:
                srv.last_error = None          # column reflects the LATEST state (executor semantics)
            last_error = srv.last_error
            await db.commit()
        else:
            last_error = err_text

    proxy = manager.proxy_source(server_id)    # PB-1 context; None = never launched this process
    return {"id": server_id, "label": label, "transport": transport,
            "health_status": health, "last_checked_at": now.isoformat(),
            "last_error": last_error, "tool_count": tool_count,
            "proxy_source": proxy or "unknown"}


async def check_health_all() -> None:
    """Boot-time sweep (ARSLAN_MCP_HEALTH_ON_BOOT=1): probe every registered server once,
    sequentially, each with the same 10s bound. Fail-open — one bad server never blocks
    the next, and callers wrap the whole sweep so boot can never fail on it."""
    async with db_session.AsyncSessionLocal() as db:
        ids = [r[0] for r in (await db.execute(select(MCPServer.id).order_by(MCPServer.id))).all()]
    for sid in ids:
        try:
            await check_health(sid)
        except Exception as exc:  # noqa: BLE001 — sweep is best-effort
            logger.warning("mcp boot health probe failed for server %s: %s", sid, exc)


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
