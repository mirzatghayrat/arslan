"""Arslan Hands for the UI and the desktop shell (0.1.53).

- `GET  /hands`            — available? switch, cursor, never-lists, Accessibility (if Hands runs)
- `PUT  /hands`            — the switch, the cursor overlay, the user's own never-list
- `POST /hands/stop`       — stop every Hands action now (island, menu bar)
- `POST /hands/check`      — start Hands if needed and report whether it has Accessibility
- `POST /hands/permission` — ask Hands to show macOS's Accessibility prompt (D3)
- `GET  /hands/trace`      — the last seven days of Hands calls (Activity)

Loopback + the API token, like every router here.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from server.auth import require_auth
from server.services import hands_client, hands_service

router = APIRouter(dependencies=[Depends(require_auth)])


class HandsSettings(BaseModel):
    enabled: bool | None = None
    cursor: bool | None = None
    never: list[str] | None = Field(default=None, max_length=hands_service.MAX_NEVER)


async def _status(start: bool) -> dict:
    if not hands_client.available():
        return {"running": False}
    try:
        reply = await hands_client.call("status", {}, timeout=10, start=start)
    except hands_client.HandsUnavailable as exc:
        return {"running": False, "error": str(exc)[:200]}
    return {"running": True, "accessibility": bool(reply.get("accessibility")),
            "peer_check": reply.get("peer_check"), "version": reply.get("version")}


@router.get("/hands")
async def get_hands() -> dict:
    status = await _status(start=False) if hands_client.running() else {"running": False}
    return {"available": hands_client.available(), **hands_service.settings(),
            "built_in": hands_service.built_in_lists(), **status}


@router.put("/hands")
async def put_hands(body: HandsSettings) -> dict:
    updated = hands_service.update_settings(enabled=body.enabled, cursor=body.cursor, never=body.never)
    return {"available": hands_client.available(), **updated, "built_in": hands_service.built_in_lists()}


@router.post("/hands/stop")
async def stop_hands() -> dict:
    """Every job running now refuses further Hands calls; the command in flight is
    killed. Jobs started afterwards are not affected."""
    jobs = hands_service.stop_running_jobs()
    killed = False
    if hands_client.running():
        try:
            reply = await hands_client.call("stop", {}, timeout=5, start=False)
            killed = bool(reply.get("killed"))
        except hands_client.HandsUnavailable:
            pass
    return {"stopped": True, "jobs": len(jobs), "killed": killed}


@router.get("/hands/takeover")
async def takeover_status() -> dict:
    """Hands v2 §6.4: whether a job has the screen, and whether it is paused (for the island)."""
    if not hands_client.running():
        return {"active": False}
    try:
        reply = await hands_client.call("takeover_status", {}, timeout=5, start=False)
    except hands_client.HandsUnavailable:
        return {"active": False}
    return reply.get("takeover") or {"active": False}


@router.post("/hands/takeover/continue")
async def takeover_continue() -> dict:
    """The user let the paused takeover go on (the island's 继续)."""
    try:
        reply = await hands_client.call("takeover_resume", {}, timeout=5, start=False)
    except hands_client.HandsUnavailable as exc:
        return {"ok": False, "error": str(exc)[:200]}
    return {"ok": bool(reply.get("ok")), **(reply.get("takeover") or {}),
            **({"code": (reply.get("refused") or {}).get("code")} if not reply.get("ok") else {})}


@router.post("/hands/takeover/end")
async def takeover_end() -> dict:
    """The user took the screen back (the island's 停止 for the takeover; the job carries on in
    the background or reports)."""
    try:
        reply = await hands_client.call("takeover_end", {}, timeout=5, start=False)
    except hands_client.HandsUnavailable as exc:
        return {"ok": False, "error": str(exc)[:200]}
    return {"ok": True, "ended": bool(reply.get("ended"))}


@router.post("/hands/check")
async def check_hands() -> dict:
    return await _status(start=True)


@router.post("/hands/permission")
async def ask_permission() -> dict:
    if not hands_client.available():
        return {"accessibility": False, "available": False}
    try:
        reply = await hands_client.call("request_permission", {}, timeout=10)
    except hands_client.HandsUnavailable as exc:
        return {"accessibility": False, "error": str(exc)[:200]}
    return {"accessibility": bool(reply.get("accessibility"))}


@router.get("/hands/trace")
async def get_trace(days: int = Query(hands_service.TRACE_DAYS, ge=1, le=hands_service.TRACE_DAYS),
                    limit: int = Query(200, ge=1, le=500)) -> dict:
    return {"entries": hands_service.read_trace(days, limit)}
