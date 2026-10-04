"""The desktop shell's one window into the backend while its window is hidden (0.1.41).

Loopback + the existing API token (router-level `require_auth`). Returns counts,
the two desktop settings, and notification events newer than `after`. Events
never carry message text: a conversation's "title" is the start of its first
user message, so only a scheduled task's user-chosen name is included.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.models import ScheduledTask
from server.db.session import get_session
from server.services import desktop_status, settings_service

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/desktop/status")
async def get_desktop_status(after: int = Query(0, ge=0),
                             db: AsyncSession = Depends(get_session)) -> dict:
    snapshot = desktop_status.snapshot(after)
    task_ids = {e["task_id"] for e in snapshot["events"] if e.get("task_id") is not None}
    names: dict[int, str] = {}
    if task_ids:
        rows = await db.execute(select(ScheduledTask.id, ScheduledTask.name)
                                .where(ScheduledTask.id.in_(task_ids)))
        names = {task_id: (name or "")[:80] for task_id, name in rows.all()}
    for event in snapshot["events"]:
        event["task_name"] = names.get(event.get("task_id"), "") if event.get("task_id") else ""
    snapshot["keep_awake"] = await settings_service.keep_awake_enabled(db)
    snapshot["notifications"] = await settings_service.desktop_notifications_enabled(db)
    # Mobile bridge §6.1: the shell starts the Arslan Bridge only while this is on.
    snapshot["phone_bridge"] = await settings_service.phone_bridge_enabled(db)
    return snapshot


@router.get("/island/feed")
async def get_island_feed(after: int = Query(0, ge=0),
                          db: AsyncSession = Depends(get_session)) -> dict:
    """The on-screen island (0.1.51 I1): work in flight with its latest step and
    plan, cards waiting, recent events with a title and summary. Unlike the status
    endpoint (read for notifications that can show on a locked screen), this one is
    read only by the island, which macOS keeps out of screenshots and shares."""
    feed = desktop_status.island_feed(after)
    task_ids = {e["task_id"] for e in feed["events"] if e.get("task_id") is not None}
    if task_ids:
        rows = await db.execute(select(ScheduledTask.id, ScheduledTask.name)
                                .where(ScheduledTask.id.in_(task_ids)))
        names = {task_id: (name or "")[:80] for task_id, name in rows.all()}
        for event in feed["events"]:
            if event.get("task_id") is not None and not event.get("title"):
                event["title"] = names.get(event["task_id"]) or None
    feed["enabled"] = await settings_service.island_enabled(db)
    return feed
