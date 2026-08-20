"""Arslan schedules its own work (spec P2 §1.2).

These write into the SAME `scheduled_tasks` table the user's own UI manages, so
what Arslan creates is visible and cancellable in the place the user already
looks. The gates are the scheduler's own — MIN_INTERVAL_S, MAX_ENABLED,
parse_cron — read from that module rather than copied, because a second copy of
a threshold is a second thing to drift.

spawn_id is always None: a task Arslan schedules runs as Arslan (P2 §1.1),
which also means it runs with no confirm callbacks and therefore cannot write
or execute — scheduling cannot be used to escape the interactive gates.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from sqlalchemy import func, select

from server.db import session as db_session
from server.db.models import ScheduledTask

# NOTE: `server.services.scheduler` is imported inside the functions below, not
# here. scheduler → dispatcher → spawn_loop → tool_loop → registry.executors →
# this module, so a module-level import is a cycle: importing this module
# directly raised ImportError while importing it THROUGH executors happened to
# work, which is the kind of asymmetry that hides until something imports it the
# other way round.

logger = logging.getLogger(__name__)

MAX_NAME = 80
_WHEN_RE = re.compile(r"^\s*(every|cron)\s*:\s*(.+?)\s*$", re.I)


def _parse_when(when: str) -> tuple[str, int | None, str | None, str | None]:
    """('interval'|'cron', interval_s, cron, error)."""
    from server.services import scheduler

    m = _WHEN_RE.match(when or "")
    if not m:
        return "", None, None, ("when must look like 'every: 3600' (seconds) "
                                "or 'cron: 0 9 * * *'")
    kind, rest = m.group(1).lower(), m.group(2)
    if kind == "every":
        try:
            seconds = int(rest)
        except ValueError:
            return "", None, None, f"'{rest}' is not a number of seconds"
        if seconds < scheduler.MIN_INTERVAL_S:
            return "", None, None, (f"the shortest allowed interval is "
                                    f"{scheduler.MIN_INTERVAL_S} seconds")
        return "interval", seconds, None, None
    # DELIBERATELY REDUNDANT with compute_next_due below, which also rejects an
    # unparseable expression. Either layer alone keeps a bad cron out of the DB
    # (measured: mutating one stays green, both together goes red) — this one
    # exists to give the model a message about the CRON rather than about a
    # schedule that "never comes due", which is a different and more confusing
    # complaint.
    try:
        scheduler.parse_cron(rest)
    except ValueError as exc:
        return "", None, None, f"invalid cron expression: {exc}"
    return "cron", None, rest, None


def _describe(task: ScheduledTask) -> str:
    return (f"every: {task.interval_s}" if task.schedule_kind == "interval"
            else f"cron: {task.cron}")


class ScheduleTaskExecutor:
    """Create a recurring task that runs as Arslan."""
    key = "schedule_task"

    async def execute(self, args: dict) -> dict:
        name = str(args.get("name") or "").strip()[:MAX_NAME]
        prompt = str(args.get("prompt") or "").strip()
        if not name or not prompt:
            return {"ok": False, "error": "name and prompt are required"}
        kind, interval_s, cron, err = _parse_when(str(args.get("when") or ""))
        if err:
            return {"ok": False, "error": err}
        from server.services import scheduler

        async with db_session.AsyncSessionLocal() as db:
            enabled = (await db.execute(
                select(func.count()).select_from(ScheduledTask)
                .where(ScheduledTask.enabled.is_(True)))).scalar() or 0
            if enabled >= scheduler.MAX_ENABLED:
                return {"ok": False,
                        "error": f"there are already {enabled} enabled scheduled tasks "
                                 f"(the limit is {scheduler.MAX_ENABLED}) — cancel one first"}
            task = ScheduledTask(
                name=name, prompt=prompt, spawn_id=None, target="arslan",
                conversation_id=args.get("conversation_id"),
                schedule_kind=kind, interval_s=interval_s, cron=cron,
                enabled=True, consecutive_failures=0)
            try:
                task.next_due_at = scheduler.compute_next_due(task, datetime.utcnow())
            except ValueError as exc:
                return {"ok": False, "error": f"that schedule never comes due: {exc}"}
            db.add(task)
            await db.commit()
            await db.refresh(task)
            return {"ok": True, "task_id": task.id, "name": task.name,
                    "when": _describe(task),
                    "next_due_at": task.next_due_at.isoformat() if task.next_due_at else None}


class ListTasksExecutor:
    """List the recurring tasks (Arslan's and the user's alike)."""
    key = "list_my_tasks"

    async def execute(self, args: dict) -> dict:
        async with db_session.AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(ScheduledTask).order_by(ScheduledTask.id))).scalars().all()
        return {"ok": True, "tasks": [
            {"id": t.id, "name": t.name, "when": _describe(t),
             "enabled": bool(t.enabled), "mine": (t.target or "spawn") == "arslan",
             "next_due_at": t.next_due_at.isoformat() if t.next_due_at else None}
            for t in rows]}


class CancelTaskExecutor:
    """Delete a recurring task by id."""
    key = "cancel_task"

    async def execute(self, args: dict) -> dict:
        try:
            task_id = int(args.get("task_id"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "task_id must be a number"}
        async with db_session.AsyncSessionLocal() as db:
            task = await db.get(ScheduledTask, task_id)
            if task is None:
                return {"ok": False, "error": f"no scheduled task with id {task_id}"}
            name = task.name
            await db.delete(task)
            await db.commit()
        return {"ok": True, "task_id": task_id, "name": name}
