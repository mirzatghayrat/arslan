"""The heartbeat checklist (spec P2 §1.3).

A list the user writes; on a cadence, ONE Arslan turn reads it and decides
whether anything on it needs doing right now. Implemented as an ordinary
scheduled task with target="arslan", so it inherits that path's property
wholesale: no socket, no confirm callbacks, and therefore no writes and no
commands. A heartbeat can only come back as a MESSAGE. It proposes; the user
decides.

Stored in Settings, not in a workspace file (裁决②): a checklist in a file
would make this feature require the workspace feature, coupling two things
that have no reason to be coupled — and a user who has not picked a workspace
would silently have no heartbeat.

DEFAULT OFF, and the suggested cadence is hours rather than OpenClaw's thirty
minutes (裁决③) — it is the user's machine and the user's tokens.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ScheduledTask
from server.services import settings_service

logger = logging.getLogger(__name__)

TASK_NAME = "__heartbeat__"          # reserved: identifies the one managed task
DEFAULT_INTERVAL_S = 6 * 3600        # 裁决③
MAX_CHECKLIST_CHARS = 4000


def build_prompt(checklist: str) -> str:
    """What the periodic turn is actually asked.

    Two things this must NOT do. It must not order work done — the turn cannot
    write or execute, so instructions to "fix" produce a narration of failures.
    And it must make "nothing needs doing" an acceptable answer, because a model
    asked to review a list will otherwise invent work to look useful.
    """
    return (
        "这是你和用户约定的定期检查清单。请逐条判断:现在有没有哪一条**确实**需要处理?\n\n"
        f"{checklist.strip()[:MAX_CHECKLIST_CHARS]}\n\n"
        "规则:\n"
        "- 只用只读手段核实(联网搜索、读工作区文件)。这一轮你不能写文件、不能跑命令。\n"
        "- 如果确实有事该办,说清是哪一条、你查到了什么、建议怎么做——由用户决定动不动手。\n"
        "- **如果没有一条需要处理,就直接说「暂时没有需要处理的」。**"
        "什么都不用做是完全正常的答案,不要为了显得有用而找活干。"
    )


async def _read_settings() -> tuple[bool, str, int]:
    async with db_session.AsyncSessionLocal() as db:
        enabled = await settings_service.heartbeat_enabled(db)
        checklist = await settings_service.heartbeat_checklist(db)
        interval = await settings_service.heartbeat_interval_s(db)
    return enabled, checklist, interval


async def sync_task() -> None:
    """Make the scheduled task match the settings — create, update, or remove.

    Idempotent by design: it is called after any settings change and on boot,
    and running it twice must not leave two heartbeats. An enabled heartbeat
    with an EMPTY checklist creates nothing: a task that fires forever to
    conclude "nothing to check" is spend without purpose.
    """
    from server.services import scheduler

    enabled, checklist, interval = await _read_settings()
    wanted = enabled and bool(checklist.strip())
    interval = max(interval, scheduler.MIN_INTERVAL_S)

    async with db_session.AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(ScheduledTask).where(ScheduledTask.name == TASK_NAME)
        )).scalars().first()

        if not wanted:
            if existing is not None:
                await db.delete(existing)
                await db.commit()
            return

        if existing is None:
            task = ScheduledTask(
                name=TASK_NAME, prompt=build_prompt(checklist), spawn_id=None,
                target="arslan", conversation_id=None,
                schedule_kind="interval", interval_s=interval,
                enabled=True, consecutive_failures=0)
            task.next_due_at = scheduler.compute_next_due(task, datetime.utcnow())
            db.add(task)
        else:
            existing.prompt = build_prompt(checklist)
            existing.interval_s = interval
            existing.enabled = True
            existing.consecutive_failures = 0
            existing.next_due_at = scheduler.compute_next_due(existing, datetime.utcnow())
        await db.commit()
