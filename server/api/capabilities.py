"""What Arslan can do, as switches (0.1.55 §14). See services/capability_list."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.auth import require_auth
from server.services import capability_list

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/capabilities")
async def list_capabilities() -> list[dict]:
    return await capability_list.capabilities()


class Switch(BaseModel):
    on: bool


@router.put("/capabilities/{key:path}")
async def switch_capability(key: str, body: Switch) -> dict:
    try:
        await capability_list.switch(key, body.on)
    except capability_list.NotSwitchable as exc:
        raise HTTPException(status_code=409, detail={"code": "not_switchable"}) from exc
    row = next((r for r in await capability_list.capabilities() if r["key"] == key), None)
    return row or {"key": key}


@router.get("/capability-search")
async def search_capabilities(q: str = "", kind: str | None = None) -> dict:
    """0.1.57 §2/§9: the Discover box — what you want done, across the official MCP Registry,
    GitHub and reviewed skill libraries. Read-only; nothing here installs."""
    from server.services import capability_search
    words = await capability_search.words_for(q)
    kinds = {kind} if kind in ("mcp", "skill", "project") else None
    return await capability_search.search(q, words=words, kinds=kinds)
