"""Proactivity (0.1.47): the inbox of things Arslan noticed, the watches that feed
it, and the user's choices. Every route sits behind the API token.

Nothing here acts on the world. `accept` hands an item's goal to the background-job
runner, whose own confirmations still apply; everything else only changes what is
shown or watched.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.auth import require_auth
from server.services import proactive_service as service
from server.services.proactive_service import ProactiveError

router = APIRouter(dependencies=[Depends(require_auth)])

STATUS = {"item_not_found": 404, "watch_not_found": 404, "already_handled": 409}


def fail(error: ProactiveError) -> HTTPException:
    return HTTPException(STATUS.get(error.code, 422), detail={"code": error.code})


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeenIn(Strict):
    ids: list[int] = Field(max_length=200)


class AcceptIn(Strict):
    conversation_id: str | None = Field(default=None, max_length=50)


class SnoozeIn(Strict):
    days: int


class DismissIn(Strict):
    mute: str | None = None


class WatchIn(Strict):
    kind: str
    target: str = Field(max_length=4000)
    label: str | None = Field(default=None, max_length=120)
    interval_s: int = 21600
    notify: bool = True


class WatchPatch(Strict):
    interval_s: int | None = None
    enabled: bool | None = None
    notify: bool | None = None
    label: str | None = Field(default=None, max_length=120)


@router.get("/proactive/summary")
async def summary():
    return await service.summary()


@router.get("/proactive/items")
async def list_items(scope: str = Query("open", pattern="^(open|done|snoozed|all)$"), limit: int = Query(100, ge=1, le=200)):
    return {"items": await service.list_items(scope, limit)}


@router.post("/proactive/items/seen")
async def mark_seen(body: SeenIn):
    await service.mark_seen(body.ids)
    return {"ok": True}


@router.post("/proactive/items/{item_id}/accept")
async def accept(item_id: int, body: AcceptIn):
    try:
        return await service.accept(item_id, body.conversation_id)
    except ProactiveError as error:
        raise fail(error) from error


@router.post("/proactive/items/{item_id}/snooze")
async def snooze(item_id: int, body: SnoozeIn):
    try:
        await service.snooze(item_id, body.days)
    except ProactiveError as error:
        raise fail(error) from error
    return {"ok": True}


@router.post("/proactive/items/{item_id}/dismiss")
async def dismiss(item_id: int, body: DismissIn):
    try:
        await service.dismiss(item_id, body.mute)
    except ProactiveError as error:
        raise fail(error) from error
    return {"ok": True}


@router.get("/proactive/config")
async def get_config():
    return (await service.load_config()).model_dump()


@router.put("/proactive/config")
async def put_config(patch: dict):
    try:
        return (await service.save_config(patch)).model_dump()
    except ProactiveError as error:
        raise fail(error) from error


@router.get("/proactive/watches")
async def list_watches():
    return {"watches": await service.list_watches()}


@router.post("/proactive/watches", status_code=201)
async def add_watch(body: WatchIn):
    try:
        return await service.add_watch(body.kind, body.target, label=body.label, interval_s=body.interval_s,
                                       notify=body.notify)
    except ProactiveError as error:
        raise fail(error) from error


@router.patch("/proactive/watches/{watch_id}")
async def update_watch(watch_id: int, body: WatchPatch):
    try:
        return await service.update_watch(watch_id, body.model_dump(exclude_unset=True))
    except ProactiveError as error:
        raise fail(error) from error


@router.delete("/proactive/watches/{watch_id}")
async def delete_watch(watch_id: int):
    await service.delete_watch(watch_id)
    return {"ok": True}


@router.get("/proactive/mutes")
async def list_mutes():
    return {"mutes": await service.list_mutes()}


@router.delete("/proactive/mutes")
async def unmute(key: str = Query(max_length=130)):
    await service.unmute(key)
    return {"ok": True}


@router.post("/proactive/scan")
async def scan_now():
    """Look now instead of at the next pass. Runs every detector once, even with the
    feature switched off (the user asked), and returns what was found."""
    result = await service.scan_once(manual=True)
    return {"created": len(result.get("created", [])), "rejected": result.get("rejected", {})}
