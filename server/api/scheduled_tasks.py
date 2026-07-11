"""S3-M4 Task 3: scheduled-tasks API — CRUD + pause/resume/fire-now + history.

Validation delegates to server/services/scheduler.py's primitives (parse_cron,
MIN_INTERVAL_S, MAX_ENABLED, compute_next_due) — the API never re-implements a
scheduling rule, so the loop and the API can't drift apart.

Semantics (documented decisions):
- MANUAL pause: enabled=False + next_due_at=None, paused_reason is NEVER written
  (a non-null paused_reason always means the 3-fail auto-pause). An existing
  auto-pause reason is left in place — it is still true information.
- resume: enabled=True, paused_reason=None, consecutive_failures=0, next_due_at
  recomputed FORWARD from now. For an interval task whose last fire is stale this
  fires on the next tick — DELIBERATE (review S7): the user just fixed the cause,
  an instant retry is the honest behavior. Resume counts against MAX_ENABLED.
- fire-now: single-flight respected (in-flight row → 409 "already running"),
  otherwise the EXACT same supervised _fire path the loop uses; 202 accepted.
- DELETE: the task row only — scheduled_task_runs rows go with it via the FK's
  ON DELETE CASCADE (build_engine sets PRAGMA foreign_keys=ON per connection).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db import session as db_session
from server.db.models import ScheduledTask, ScheduledTaskRun, Spawn
from server.schemas import (
    ScheduledTaskCreateIn,
    ScheduledTaskOut,
    ScheduledTaskRunOut,
    ScheduledTaskUpdateIn,
)
from server.services import scheduler

router = APIRouter(dependencies=[Depends(require_auth)])

RUNS_LIMIT = 50


def _task_out(task: ScheduledTask, *, spawn_name: str | None,
              last_outcome: str | None) -> ScheduledTaskOut:
    return ScheduledTaskOut(
        id=task.id, name=task.name, prompt=task.prompt, spawn_id=task.spawn_id,
        spawn_name=spawn_name, conversation_id=task.conversation_id,
        schedule_kind=task.schedule_kind, interval_s=task.interval_s, cron=task.cron,
        enabled=task.enabled, last_fired_at=task.last_fired_at,
        next_due_at=task.next_due_at,
        consecutive_failures=task.consecutive_failures or 0,
        paused_reason=task.paused_reason, created_at=task.created_at,
        last_outcome=last_outcome,
    )


async def _load_task(db: AsyncSession, task_id: int) -> ScheduledTask:
    task = await db.get(ScheduledTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"定时任务 {task_id} 不存在")
    return task


async def _require_spawn(db: AsyncSession, spawn_id: int) -> Spawn:
    spawn = await db.get(Spawn, spawn_id)
    if spawn is None:
        raise HTTPException(status_code=422, detail=f"spawn {spawn_id} 不存在")
    return spawn


def _validate_schedule(kind: str, interval_s: int | None, cron: str | None) -> None:
    """Schedule fields against the scheduler's own rules (single source of truth)."""
    if kind == "interval":
        if interval_s is None or interval_s < scheduler.MIN_INTERVAL_S:
            raise HTTPException(
                status_code=422,
                detail=f"interval_s 必须 >= {scheduler.MIN_INTERVAL_S} 秒(15 分钟)")
    else:  # "cron" — kinds are Literal-constrained by the schema
        if not cron:
            raise HTTPException(status_code=422, detail="cron 表达式不能为空")
        try:
            scheduler.parse_cron(cron)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _check_enabled_quota(db: AsyncSession) -> None:
    count = (await db.execute(
        select(func.count()).select_from(ScheduledTask)
        .where(ScheduledTask.enabled.is_(True))
    )).scalar() or 0
    if count >= scheduler.MAX_ENABLED:
        raise HTTPException(
            status_code=409,
            detail=f"已启用的定时任务已达上限 {scheduler.MAX_ENABLED} 个,请先暂停或删除")


def _recompute_next_due(task: ScheduledTask, now: datetime) -> None:
    """compute_next_due, surfacing 'cron never matches' as a 422 (e.g. 0 0 31 2 *
    parses fine but has no future slot within the search bound)."""
    try:
        task.next_due_at = scheduler.compute_next_due(task, now)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _latest_outcome(db: AsyncSession, task_id: int) -> str | None:
    return (await db.execute(
        select(ScheduledTaskRun.outcome)
        .where(ScheduledTaskRun.task_id == task_id)
        .order_by(ScheduledTaskRun.id.desc()).limit(1)
    )).scalar()


# ── list ─────────────────────────────────────────────────────────────────────────────

@router.get("/scheduled-tasks", response_model=list[ScheduledTaskOut])
async def list_scheduled_tasks() -> list[ScheduledTaskOut]:
    async with db_session.AsyncSessionLocal() as db:
        latest = (
            select(ScheduledTaskRun.task_id,
                   func.max(ScheduledTaskRun.id).label("latest_id"))
            .group_by(ScheduledTaskRun.task_id).subquery()
        )
        rows = (await db.execute(
            select(ScheduledTask, Spawn.name, ScheduledTaskRun.outcome)
            .outerjoin(Spawn, Spawn.id == ScheduledTask.spawn_id)
            .outerjoin(latest, latest.c.task_id == ScheduledTask.id)
            .outerjoin(ScheduledTaskRun, ScheduledTaskRun.id == latest.c.latest_id)
            .order_by(ScheduledTask.id)
        )).all()
    return [_task_out(task, spawn_name=spawn_name, last_outcome=outcome)
            for task, spawn_name, outcome in rows]


# ── create / update / delete ─────────────────────────────────────────────────────────

@router.post("/scheduled-tasks", response_model=ScheduledTaskOut, status_code=201)
async def create_scheduled_task(body: ScheduledTaskCreateIn) -> ScheduledTaskOut:
    async with db_session.AsyncSessionLocal() as db:
        spawn = await _require_spawn(db, body.spawn_id)
        _validate_schedule(body.schedule_kind, body.interval_s, body.cron)
        await _check_enabled_quota(db)
        task = ScheduledTask(
            name=body.name, prompt=body.prompt, spawn_id=body.spawn_id,
            conversation_id=body.conversation_id, schedule_kind=body.schedule_kind,
            interval_s=body.interval_s, cron=body.cron,
            enabled=True, consecutive_failures=0)
        _recompute_next_due(task, datetime.utcnow())
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return _task_out(task, spawn_name=spawn.name, last_outcome=None)


@router.put("/scheduled-tasks/{task_id}", response_model=ScheduledTaskOut)
async def update_scheduled_task(task_id: int,
                                body: ScheduledTaskUpdateIn) -> ScheduledTaskOut:
    async with db_session.AsyncSessionLocal() as db:
        task = await _load_task(db, task_id)
        data = body.model_dump(exclude_unset=True)
        if "spawn_id" in data and data["spawn_id"] is not None:
            await _require_spawn(db, data["spawn_id"])
        # Validate the EFFECTIVE schedule (current row + patch), then recompute
        # next_due_at only when the schedule actually changed.
        kind = data.get("schedule_kind") or task.schedule_kind
        interval_s = data.get("interval_s", task.interval_s)
        cron = data.get("cron", task.cron)
        changed = (kind, interval_s, cron) != (task.schedule_kind, task.interval_s,
                                               task.cron)
        if changed:
            _validate_schedule(kind, interval_s, cron)
        for key, value in data.items():
            setattr(task, key, value)
        if changed:
            _recompute_next_due(task, datetime.utcnow())
        await db.commit()
        await db.refresh(task)
        spawn = None if task.spawn_id is None else await db.get(Spawn, task.spawn_id)
        outcome = await _latest_outcome(db, task_id)
        return _task_out(task, spawn_name=spawn.name if spawn else None,
                         last_outcome=outcome)


@router.delete("/scheduled-tasks/{task_id}")
async def delete_scheduled_task(task_id: int) -> dict:
    async with db_session.AsyncSessionLocal() as db:
        task = await _load_task(db, task_id)
        await db.delete(task)   # runs rows CASCADE via FK (PRAGMA foreign_keys=ON)
        await db.commit()
    return {"ok": True}


# ── pause / resume / fire-now ────────────────────────────────────────────────────────

@router.post("/scheduled-tasks/{task_id}/pause", response_model=ScheduledTaskOut)
async def pause_scheduled_task(task_id: int) -> ScheduledTaskOut:
    """Manual pause: enabled=False, next_due cleared. paused_reason is NOT written —
    None reason + disabled = the user's own pause; non-null = auto-pause."""
    async with db_session.AsyncSessionLocal() as db:
        task = await _load_task(db, task_id)
        task.enabled = False
        task.next_due_at = None
        await db.commit()
        await db.refresh(task)
        spawn = None if task.spawn_id is None else await db.get(Spawn, task.spawn_id)
        outcome = await _latest_outcome(db, task_id)
        return _task_out(task, spawn_name=spawn.name if spawn else None,
                         last_outcome=outcome)


@router.post("/scheduled-tasks/{task_id}/resume", response_model=ScheduledTaskOut)
async def resume_scheduled_task(task_id: int) -> ScheduledTaskOut:
    """Resume: clear the pause bookkeeping and recompute next_due FORWARD from now.
    After an auto-pause of a stale interval task this fires on the next tick —
    DELIBERATE (review S7). Counts against the MAX_ENABLED quota."""
    async with db_session.AsyncSessionLocal() as db:
        task = await _load_task(db, task_id)
        if not task.enabled:
            await _check_enabled_quota(db)
        task.enabled = True
        task.paused_reason = None
        task.consecutive_failures = 0
        _recompute_next_due(task, datetime.utcnow())
        await db.commit()
        await db.refresh(task)
        spawn = None if task.spawn_id is None else await db.get(Spawn, task.spawn_id)
        outcome = await _latest_outcome(db, task_id)
        return _task_out(task, spawn_name=spawn.name if spawn else None,
                         last_outcome=outcome)


@router.post("/scheduled-tasks/{task_id}/fire-now", status_code=202)
async def fire_scheduled_task_now(task_id: int) -> dict:
    """Fire immediately, bypassing next_due — the same supervised _fire the loop
    uses (in-flight row first, S6 outcome bookkeeping, 3-fail auto-pause all apply).
    Single-flight is respected: an in-flight run → 409."""
    async with db_session.AsyncSessionLocal() as db:
        task = await _load_task(db, task_id)
    if await scheduler.has_inflight(task_id):
        raise HTTPException(status_code=409, detail="already running")
    scheduler._supervise(scheduler._fire(task))
    return {"status": "accepted", "task_id": task_id}


# ── history ──────────────────────────────────────────────────────────────────────────

@router.get("/scheduled-tasks/{task_id}/runs",
            response_model=list[ScheduledTaskRunOut])
async def scheduled_task_runs(task_id: int) -> list[ScheduledTaskRunOut]:
    async with db_session.AsyncSessionLocal() as db:
        await _load_task(db, task_id)
        rows = (await db.execute(
            select(ScheduledTaskRun)
            .where(ScheduledTaskRun.task_id == task_id)
            .order_by(ScheduledTaskRun.id.desc()).limit(RUNS_LIMIT)
        )).scalars().all()
    return [ScheduledTaskRunOut(id=r.id, started_at=r.started_at,
                                finished_at=r.finished_at, outcome=r.outcome,
                                run_id=r.run_id, reason=r.reason) for r in rows]
