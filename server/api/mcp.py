"""MCP server config + connect/expose/wire/health endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.auth import require_auth
from server.mcp import catalog
from server.services import mcp_service

# PB-4 条件3: the health probe must sit behind require_auth. The MCP router historically
# carried NO auth dependency at all (unlike facts/create/skills/…), so we close the gap
# router-wide — require_auth is a no-op when ARSLAN_API_TOKEN is unset, and the web client
# always attaches the Bearer token, so existing callers are unaffected.
router = APIRouter(prefix="/mcp", tags=["mcp"], dependencies=[Depends(require_auth)])


class AddServerBody(BaseModel):
    label: str
    command: str = ""
    args: list[str] = []
    env: dict[str, str] = {}
    transport: str = "stdio"
    url: str | None = None


class ExposeBody(BaseModel):
    exposed: bool


class WireBody(BaseModel):
    tier: str
    wired: bool


class HostBody(BaseModel):
    enabled: bool


@router.post("/servers")
async def add_server(body: AddServerBody):
    return await mcp_service.add_server(body.label, body.command, body.args, body.env,
                                        transport=body.transport, url=body.url)


@router.get("/servers")
async def list_servers():
    return await mcp_service.list_servers()


@router.get("/catalog")
async def get_catalog():
    """Preset connector catalog (single source; also feeds the Settings recommended list)."""
    return catalog.list_connectors()


#: In-memory flow states — one interactive authorization at a time per server.
#: In-memory ON PURPOSE: a flow is bound to a live loopback listener in this
#: process; persisting "waiting" across a restart would advertise a callback
#: port nobody is listening on.
_oauth_flows: dict[int, dict] = {}


@router.post("/servers/{server_id}/oauth/authorize")
async def start_oauth(server_id: int):
    """Kick the interactive flow; answer with the URL the browser must open.

    The URL travels backend → this response → the shell's open_external and
    nowhere else (ruling ③A's provenance half: nothing between the SDK and the
    doorway may invent one). The flow itself finishes in the background; poll
    /oauth/status for the outcome.
    """
    import asyncio

    from server.mcp import oauth_flow

    from server.db import session as db_session
    from server.db.models import MCPServer
    from server.mcp.discovery import runtime_dict

    async with db_session.AsyncSessionLocal() as db:
        srv = await db.get(MCPServer, server_id)
        if srv is None:
            raise HTTPException(status_code=404, detail=f"mcp server {server_id} not found")
        # runtime_dict, not the masked API shape: the flow needs the real URL
        # and (decrypted) headers, same as every other connect path.
        server = runtime_dict(srv)

    url_ready: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    _oauth_flows[server_id] = {"state": "waiting", "error": ""}

    async def on_auth_url(url: str) -> None:
        if not url_ready.done():
            url_ready.set_result(url)

    async def run() -> None:
        try:
            await oauth_flow.authorize(server, on_auth_url=on_auth_url)
            _oauth_flows[server_id] = {"state": "done", "error": ""}
        except Exception as exc:  # noqa: BLE001 — the outcome IS the payload here
            _oauth_flows[server_id] = {"state": "error", "error": str(exc)[:500] or type(exc).__name__}
            if not url_ready.done():
                url_ready.set_exception(exc)

    task = asyncio.create_task(run())
    _oauth_flows[server_id]["task"] = task
    try:
        auth_url = await asyncio.wait_for(asyncio.shield(url_ready), timeout=15.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="the provider never produced an authorization URL")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)[:500] or type(exc).__name__)
    return {"auth_url": auth_url}


@router.get("/servers/{server_id}/oauth/status")
async def oauth_status(server_id: int):
    st = _oauth_flows.get(server_id) or {"state": "idle", "error": ""}
    return {"state": st["state"], "error": st.get("error", "")}


@router.post("/servers/{server_id}/connect")
async def connect(server_id: int):
    return await mcp_service.connect(server_id)


@router.get("/servers/{server_id}/tools")
async def list_tools(server_id: int):
    return await mcp_service.list_tools(server_id)


@router.patch("/servers/{server_id}/expose")
async def expose(server_id: int, body: ExposeBody):
    await mcp_service.set_exposed(server_id, body.exposed)
    return {"ok": True}


@router.patch("/tools/{tool_key}/wire")
async def wire(tool_key: str, body: WireBody):
    await mcp_service.wire_tool(tool_key, body.tier, body.wired)
    return {"ok": True}


@router.patch("/tools/{tool_key}/host")
async def set_host(tool_key: str, body: HostBody):
    await mcp_service.set_host_enabled(tool_key, body.enabled)
    return {"ok": True}


@router.post("/{server_id}/health")
async def check_health(server_id: int):
    """PB-4 on-demand equipment health probe (bounded list_tools; writes status columns)."""
    try:
        return await mcp_service.check_health(server_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/servers/{server_id}/reconnect")
async def reconnect(server_id: int):
    await mcp_service.reconnect(server_id)
    return {"ok": True}


@router.delete("/servers/{server_id}")
async def delete_server(server_id: int):
    await mcp_service.delete_server(server_id)
    return {"ok": True}
