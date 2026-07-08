"""MCP server config + connect/expose/wire/health endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.auth import require_auth
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
