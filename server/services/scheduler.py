"""S3-M4 scheduled tasks — pure scheduling core (Task 1: NO run loop here yet).

Cadence semantics (approved decision D1 + spec):
- `next_due_at` is data-driven and persisted on the task row, so a restart resumes
  cleanly from the DB.
- MISSED FIRES ARE NOT REPLAYED: `compute_next_due` always computes FORWARD from
  `now` — a task whose next_due_at is 3 days stale fires ONCE and then moves on
  (matching Claude Code / OpenClaw semantics per spec). No catch-up, ever.
- Guardrails: interval tasks must be >= MIN_INTERVAL_S (15 min); at most
  MAX_ENABLED (10) tasks may be enabled. The constants live here so the service
  layer and the API validate against the same source of truth.
- Single-flight: an in-flight scheduled_task_runs row (outcome IS NULL) gates the
  task — an overlapping due fire records a 'skipped_overlap' row instead of
  dispatching.
- 3 consecutive failures auto-pause the task (enabled=False + paused_reason) and
  post a notification message into the task's conversation + a best-effort
  conversation_events entry. Notification failure NEVER breaks the outcome write.

Cron grammar (YAGNI, self-written — no dependency): 5 fields 分 时 日 月 周; each
field is `*`, a plain number (range-checked 0-59 / 0-23 / 1-31 / 1-12 / 0-6 with
0=Sunday), `*/n` (n>0), or a comma list of numbers. No ranges, no names. When BOTH
day-of-month and day-of-week are restricted, a day matches if EITHER does (standard
vixie-cron rule).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ScheduledTask, ScheduledTaskRun
from server.orchestrator import memory
from server.services import recap_service

logger = logging.getLogger(__name__)

MIN_INTERVAL_S = 900        # D1: interval tasks fire at most every 15 minutes
MAX_ENABLED = 10            # D1: at most 10 enabled tasks
PAUSE_AFTER_FAILURES = 3    # D1: auto-pause after 3 consecutive failures

# (lo, hi) per cron field: 分 时 日 月 周 (dow 0=Sunday..6=Saturday)
_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
_FIELD_NAMES = ("minute", "hour", "day-of-month", "month", "day-of-week")
_MAX_CRON_SEARCH = timedelta(days=366)

# A parsed cron spec: 5 entries, each None (wildcard) or a frozenset of allowed ints.
CronSpec = tuple["frozenset[int] | None", ...]


# ── cron parsing ─────────────────────────────────────────────────────────────────────

def _parse_field(raw: str, lo: int, hi: int, name: str) -> frozenset[int] | None:
    if raw == "*":
        return None
    if raw.startswith("*/"):
        step = raw[2:]
        if not step.isdigit() or int(step) == 0:
            raise ValueError(f"cron {name} field: bad step {raw!r} (need */n with n>0)")
        return frozenset(range(lo, hi + 1, int(step)))
    values: set[int] = set()
    for part in raw.split(","):
        if not part.isdigit():
            raise ValueError(f"cron {name} field: bad value {part!r} in {raw!r}")
        v = int(part)
        if not lo <= v <= hi:
            raise ValueError(f"cron {name} field: {v} out of range {lo}-{hi}")
        values.add(v)
    return frozenset(values)


def parse_cron(expr: str) -> CronSpec:
    """Parse a 5-field cron expression (分 时 日 月 周) or raise ValueError.

    Grammar per field: `*` | number | `*/n` | comma list of numbers. Nothing more."""
    fields = (expr or "").split()
    if len(fields) != 5:
        raise ValueError(
            f"cron expression must have 5 fields (分 时 日 月 周), got {len(fields)}: {expr!r}")
    return tuple(_parse_field(raw, lo, hi, name)
                 for raw, (lo, hi), name in zip(fields, _FIELD_RANGES, _FIELD_NAMES))


def _day_matches(spec: CronSpec, dt: datetime) -> bool:
    _, _, dom, month, dow = spec
    if month is not None and dt.month not in month:
        return False
    dom_ok = dom is None or dt.day in dom
    dow_ok = dow is None or ((dt.weekday() + 1) % 7) in dow  # python Mon=0 -> cron Sun=0
    if dom is not None and dow is not None:
        return dom_ok or dow_ok  # vixie-cron: both restricted -> either matches
    return dom_ok and dow_ok


def cron_next(expr: str, after: datetime) -> datetime:
    """Next minute matching `expr` STRICTLY after `after`.

    Iterates minute-by-minute (skipping whole non-matching days) with a ~366-day
    bound; raises ValueError when nothing matches (e.g. `0 0 31 2 *`). Simple and
    correct beats clever."""
    spec = parse_cron(expr)
    minute, hour = spec[0], spec[1]
    cur = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = cur + _MAX_CRON_SEARCH
    while cur <= end:
        if not _day_matches(spec, cur):
            cur = datetime(cur.year, cur.month, cur.day) + timedelta(days=1)
            continue
        if ((minute is None or cur.minute in minute)
                and (hour is None or cur.hour in hour)):
            return cur
        cur += timedelta(minutes=1)
    raise ValueError(f"cron expression {expr!r} never matches within 366 days")


# ── due computation (NO catch-up) ────────────────────────────────────────────────────

def compute_next_due(task: ScheduledTask, now: datetime) -> datetime | None:
    """Next fire time for `task`, or None when disabled.

    ALWAYS computed forward from `now` — missed fires are not replayed:
    - interval: max((last_fired_at or now) + interval_s, now) — a stale task is due
      once, immediately, not once per missed period;
    - cron: the next matching slot after max(last_fired_at or now, now) — the slots
      missed while down are simply skipped."""
    if not task.enabled:
        return None
    if task.schedule_kind == "interval":
        base = task.last_fired_at or now
        return max(base + timedelta(seconds=int(task.interval_s or 0)), now)
    return cron_next(task.cron or "", max(task.last_fired_at or now, now))


async def due_tasks(now: datetime) -> list[ScheduledTask]:
    """Enabled tasks whose persisted next_due_at has arrived (oldest due first)."""
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ScheduledTask)
            .where(ScheduledTask.enabled.is_(True),
                   ScheduledTask.next_due_at.is_not(None),
                   ScheduledTask.next_due_at <= now)
            .order_by(ScheduledTask.next_due_at)
        )).scalars().all()
    return list(rows)


# ── single-flight ────────────────────────────────────────────────────────────────────

async def has_inflight(task_id: int) -> bool:
    """True when the task has an unfinalized run row (outcome IS NULL)."""
    async with db_session.AsyncSessionLocal() as db:
        row_id = (await db.execute(
            select(ScheduledTaskRun.id)
            .where(ScheduledTaskRun.task_id == task_id,
                   ScheduledTaskRun.outcome.is_(None))
            .limit(1)
        )).scalar()
    return row_id is not None


async def record_skip_overlap(task_id: int) -> None:
    """Record that a due fire was skipped because the previous run is still in flight."""
    now = datetime.utcnow()
    async with db_session.AsyncSessionLocal() as db:
        db.add(ScheduledTaskRun(task_id=task_id, started_at=now, finished_at=now,
                                outcome="skipped_overlap",
                                reason="previous run still in flight"))
        await db.commit()


# ── outcome bookkeeping (ok-reset / 3-fail auto-pause) ───────────────────────────────

async def record_outcome(task_id: int, ok: bool, *, run_id: int | None = None,
                         reason: str | None = None) -> None:
    """Finalize the task's in-flight run row and update the task's scheduler state.

    ok: reset consecutive_failures, stamp last_fired_at, recompute + persist
    next_due_at (forward from now — no catch-up). fail: increment
    consecutive_failures; at PAUSE_AFTER_FAILURES the task is auto-paused
    (enabled=False, paused_reason, next_due_at=None) and the target conversation is
    notified — notification is best-effort and never breaks the outcome write."""
    now = datetime.utcnow()
    notify: tuple[str, str] | None = None  # (conversation_id, task_name)
    async with db_session.AsyncSessionLocal() as db:
        task = await db.get(ScheduledTask, task_id)
        if task is None:
            logger.warning("record_outcome for unknown scheduled task %s", task_id)
            return
        row = (await db.execute(
            select(ScheduledTaskRun)
            .where(ScheduledTaskRun.task_id == task_id,
                   ScheduledTaskRun.outcome.is_(None))
            .order_by(ScheduledTaskRun.id.desc())
            .limit(1)
        )).scalars().first()
        if row is not None:
            row.outcome = "ok" if ok else "error"
            row.finished_at = now
            row.run_id = run_id
            row.reason = (reason or "")[:2000]
        if ok:
            task.consecutive_failures = 0
            task.last_fired_at = now
            task.next_due_at = compute_next_due(task, now)
        else:
            task.consecutive_failures = (task.consecutive_failures or 0) + 1
            if task.consecutive_failures >= PAUSE_AFTER_FAILURES:
                task.enabled = False
                task.paused_reason = (
                    f"连续失败 {task.consecutive_failures} 次:{(reason or '')[:500]}")
                task.next_due_at = None
                notify = (task.conversation_id or f"scheduled-{task.id}", task.name)
        await db.commit()
    if notify is not None:
        await _notify_pause(notify[0], notify[1], reason or "", task_id=task_id)


async def _notify_pause(conversation_id: str, name: str, reason: str, *,
                        task_id: int) -> None:
    """Post the auto-pause notice into the task's conversation + recap timeline.

    Runs AFTER the outcome commit and every step is individually best-effort — a
    dead socket / locked events table must never undo the pause bookkeeping."""
    try:
        await memory.add_message(
            conversation_id, "arslan",
            f"定时任务「{name}」连续失败 {PAUSE_AFTER_FAILURES} 次,已自动暂停:{reason}")
    except Exception as exc:  # noqa: BLE001 — notification must not break the outcome write
        logger.warning("scheduled-task pause notification failed (non-fatal): %s", exc)
    try:
        await recap_service.log_event(
            conversation_id, "scheduled_pause", {"task_id": task_id},
            f"定时任务「{name}」连续失败已自动暂停")
    except Exception as exc:  # noqa: BLE001 — timeline logging is never fatal
        logger.warning("scheduled-task pause log_event failed (non-fatal): %s", exc)
