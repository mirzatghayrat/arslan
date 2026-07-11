"""S3-M4 scheduled tasks — scheduling core + supervised execution loop.

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
  dispatching AND advances next_due_at past now (review I3: ONE skip row per due
  period, not one per 60s tick).
- 3 consecutive failures auto-pause the task (enabled=False + paused_reason) and
  post a notification message into the task's conversation + a best-effort
  conversation_events entry. Notification failure NEVER breaks the outcome write.
  A resume (Task 3 API) recomputes next_due from now — for an interval task whose
  last fire is stale that means it fires on the next tick. DELIBERATE (review S7):
  the user just fixed the cause, an instant retry is the honest behavior.
- Orphan sweep (review I2): in-flight rows never survive a process restart (same
  invariant as run_reaper.mark_interrupted_runs) — watch_loop finalizes them as
  outcome='error' reason='orphaned by restart' BEFORE its first tick, so a crash
  mid-run can never wedge a task forever.

Cron grammar (YAGNI, self-written — no dependency): 5 fields 分 时 日 月 周; each
field is `*`, a plain number (range-checked 0-59 / 0-23 / 1-31 / 1-12 / 0-6 with
0=Sunday), `*/n` (n>0), or a comma list of numbers. No ranges, no names. When BOTH
day-of-month and day-of-week are restricted, a day matches if EITHER does (standard
vixie-cron rule).

Cron time base (review I5, local-first product): cron expressions are interpreted
in the USER'S LOCAL wall clock — "0 9 * * *" means 9am where the user sits.
Matching happens in local time via the `_to_local`/`_to_utc` seams (DST-aware
through the system tz database); the matched instant is converted back to
utc-naive for storage, so `next_due_at`/`due_tasks` comparisons against
`utcnow()` are untouched. Interval tasks are pure durations and unaffected.
(Task 4 UI: label cron inputs "按本地时间解释".)

Execution (Task 2): `watch_loop` ticks every 60s; each due task `_fire`s as a
SUPERVISED asyncio task (evolution_watcher's pattern — done-callback logs, never a
bare fire-and-forget). A fire is HEADLESS: deliberately NOT arslan._dispatch_spawn
(its roster-join / routing-announcement side effects are wrong here) but the M1-M3
seam directly — RunRecorder.start(kind='scheduled') + dispatcher.dispatch(run_id=…)
with frames fanned out through run_registry.make_emit (online users see the stream
live; offline it lands in the conversation for next open). kind='scheduled' NEVER
enters the evolution corpus — replay_set/evolution_watcher filter kind=='live'
(structurally pinned in tests).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from arslan.llm import usage_sink
from server.db import session as db_session
from server.db.models import ScheduledTask, ScheduledTaskRun
from server.orchestrator import dispatcher, memory, run_trace
from server.services import recap_service, run_recorder, run_registry

logger = logging.getLogger(__name__)

MIN_INTERVAL_S = 900        # D1: interval tasks fire at most every 15 minutes
MAX_ENABLED = 10            # D1: at most 10 enabled tasks
PAUSE_AFTER_FAILURES = 3    # D1: auto-pause after 3 consecutive failures
DEFAULT_INTERVAL = 60.0     # tick cadence; injectable (short in tests)

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


# ── local-time seams (review I5) ─────────────────────────────────────────────────────
# Tiny, monkeypatchable conversion seams. astimezone() presumes a naive datetime is in
# the SYSTEM timezone (python docs) — exactly the local-first contract we want, and it
# is DST-aware through the tz database (no fixed-offset arithmetic).

def _to_local(utc_naive: datetime) -> datetime:
    """utc-naive (storage) → the user's local wall time (naive)."""
    return utc_naive.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def _to_utc(local_naive: datetime) -> datetime:
    """Local wall time (naive) → utc-naive (storage)."""
    return local_naive.astimezone(timezone.utc).replace(tzinfo=None)


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
    """Next minute matching `expr` STRICTLY after `after` (both utc-naive).

    I5: `after` is converted to LOCAL wall time, the search runs in local time
    (cron means the user's clock), and the match converts back to utc-naive for
    storage. Iterates minute-by-minute (skipping whole non-matching days) with a
    ~366-day bound; raises ValueError when nothing matches (e.g. `0 0 31 2 *`).
    Simple and correct beats clever."""
    spec = parse_cron(expr)
    minute, hour = spec[0], spec[1]
    cur = _to_local(after).replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = cur + _MAX_CRON_SEARCH
    while cur <= end:
        if not _day_matches(spec, cur):
            cur = datetime(cur.year, cur.month, cur.day) + timedelta(days=1)
            continue
        if ((minute is None or cur.minute in minute)
                and (hour is None or cur.hour in hour)):
            return _to_utc(cur)
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


def _pause_no_future(task: ScheduledTask, exc: ValueError) -> None:
    """I1: a cron with no future match must PAUSE the task — never raise out of an
    outcome/skip write (an unhandled raise there would leave the in-flight row NULL
    forever and wedge the task)."""
    task.enabled = False
    task.paused_reason = f"cron 无未来匹配: {exc}"
    task.next_due_at = None


def _next_due_after(task: ScheduledTask, now: datetime) -> datetime:
    """Next slot STRICTLY after `now`, ignoring last_fired_at — used when a skip
    consumes the due period (I3): interval anchors at now, cron takes the next slot."""
    if task.schedule_kind == "interval":
        return now + timedelta(seconds=int(task.interval_s or 0))
    return cron_next(task.cron or "", now)


async def record_skip_overlap(task_id: int) -> None:
    """Record that a due fire was skipped because the previous run is still in flight.

    I3: ALSO advances next_due_at past now, so a long-running fire produces ONE
    skipped_overlap row per due period — not one per 60s tick."""
    now = datetime.utcnow()
    async with db_session.AsyncSessionLocal() as db:
        db.add(ScheduledTaskRun(task_id=task_id, started_at=now, finished_at=now,
                                outcome="skipped_overlap",
                                reason="previous run still in flight"))
        task = await db.get(ScheduledTask, task_id)
        if task is not None:
            try:
                task.next_due_at = _next_due_after(task, now)
            except ValueError as exc:
                _pause_no_future(task, exc)
        await db.commit()


async def sweep_orphans() -> int:
    """I2: finalize in-flight rows left behind by a dead process (outcome='error',
    reason='orphaned by restart') so the single-flight gate can never wedge a task
    forever. Runs never survive a restart — the same invariant as
    run_reaper.mark_interrupted_runs. Returns how many rows were swept."""
    now = datetime.utcnow()
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ScheduledTaskRun).where(ScheduledTaskRun.outcome.is_(None))
        )).scalars().all()
        for row in rows:
            row.outcome = "error"
            row.finished_at = now
            row.reason = "orphaned by restart"
        await db.commit()
    if rows:
        logger.info("scheduler: swept %d orphaned in-flight run row(s)", len(rows))
    return len(rows)


# ── outcome bookkeeping (ok-reset / 3-fail auto-pause) ───────────────────────────────

async def record_outcome(task_id: int, ok: bool, *, row_id: int,
                         run_id: int | None = None,
                         reason: str | None = None) -> None:
    """Finalize the EXPLICIT in-flight run row `row_id` and update the task's state.

    S6: the caller passes the row id its own insert returned — never "the latest
    NULL row" — so a fire-now racing a tick can never cross-attach outcomes.

    ok: reset consecutive_failures, stamp last_fired_at, recompute + persist
    next_due_at (forward from now — no catch-up; I1: a cron with no future match
    pauses the task instead of raising). fail: increment consecutive_failures; at
    PAUSE_AFTER_FAILURES the task is auto-paused (enabled=False, paused_reason,
    next_due_at=None) and the target conversation is notified — notification is
    best-effort and never breaks the outcome write."""
    now = datetime.utcnow()
    notify: tuple[str, str] | None = None  # (conversation_id, task_name)
    async with db_session.AsyncSessionLocal() as db:
        task = await db.get(ScheduledTask, task_id)
        if task is None:
            logger.warning("record_outcome for unknown scheduled task %s", task_id)
            return
        row = await db.get(ScheduledTaskRun, row_id)
        if row is None or row.task_id != task_id:
            logger.warning("record_outcome: row %s missing or not of task %s",
                           row_id, task_id)
        elif row.outcome is not None:
            logger.warning("record_outcome: row %s already finalized (%s) — skipping "
                           "row write", row_id, row.outcome)
        else:
            row.outcome = "ok" if ok else "error"
            row.finished_at = now
            row.run_id = run_id
            row.reason = (reason or "")[:2000]
        if ok:
            task.consecutive_failures = 0
            task.last_fired_at = now
            try:
                task.next_due_at = compute_next_due(task, now)
            except ValueError as exc:
                _pause_no_future(task, exc)
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


# ── supervised execution (Task 2) ────────────────────────────────────────────────────
# evolution_watcher's pattern: every fire is a tracked asyncio.Task whose failure is
# LOGGED by a done-callback — never a bare fire-and-forget that swallows a crash.

_tasks: set[asyncio.Task] = set()
_loop_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


def _on_task_done(task: asyncio.Task) -> None:
    _tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("scheduler task crashed: %s", exc, exc_info=exc)


def _supervise(coro) -> asyncio.Task:
    """Launch `coro` as a tracked task whose failures are LOGGED, not lost."""
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_on_task_done)
    return task


async def _dispatch_recorded(recorder, cid: str, spawn_id: int, prompt: str) -> dict:
    """One recorded headless dispatch: frames fan out to whatever sinks are attached
    (run_registry.make_emit — online users see the stream live, zero sinks drop
    silently, the recorder journal keeps everything via tee), usage/trace collected
    per-run exactly like _dispatch_spawn, recorder finalized on BOTH exits."""
    emit = recorder.tee(run_registry.make_emit(cid))
    emit({"type": "stream_start", "source": "spawn", "spawn_id": spawn_id,
          "run_id": recorder.run_id})
    # Per-run scoping mirrors arslan._dispatch_spawn: one fresh usage bucket + tool
    # trace per Run, both still open at finalize time so detail lands on the row.
    with usage_sink.collecting(), run_trace.collecting():
        try:
            out = await dispatcher.dispatch(
                cid, spawn_id=spawn_id, task_brief=prompt,
                on_chunk=lambda c: emit({"type": "stream_chunk", "content": c}),
                on_event=emit,
                # Headless: nobody is present to resolve an escalation mid-fire, so
                # the spawn is never offered the protocol — it must complete or fail.
                allow_escalation=False,
                run_id=recorder.run_id,
            )
        except Exception as exc:  # noqa: BLE001 — finalize with error fields, then re-raise
            emit({"type": "error", "code": "SPAWN_ERROR", "message": str(exc),
                  "recoverable": True})
            _usage = usage_sink.detail()
            _prompt = run_trace.prompt()
            await recorder.finalize(
                summary_message_id=None, full_output="",
                model=_usage["model"], provider=_usage["provider"],
                tokens_in=_usage["tokens_in"], tokens_out=_usage["tokens_out"],
                tokens_estimated=(_usage["tokens_in"] is None),
                error_kind=type(exc).__name__, error_text=str(exc),
                system_prompt=_prompt["system_prompt"], injected_kb=_prompt["injected_kb"],
                injected_kb_sources=_prompt.get("injected_kb_sources"),
            )
            raise
        _usage = usage_sink.detail()
        _prompt = run_trace.prompt()
        await recorder.finalize(
            summary_message_id=out["summary_message_id"],
            full_output=out["full_output"],
            model=_usage["model"], provider=_usage["provider"],
            tokens_in=_usage["tokens_in"], tokens_out=_usage["tokens_out"],
            tokens_estimated=(_usage["tokens_in"] is None),
            system_prompt=_prompt["system_prompt"], injected_kb=_prompt["injected_kb"],
            injected_kb_sources=_prompt.get("injected_kb_sources"),
        )
    # Post-finalize close frame, exactly like _dispatch_spawn's tail: live sinks get
    # their stream closed (the persisted summary message is the durable copy).
    emit({"type": "stream_end", "message_id": out["summary_message_id"]})
    return out


async def _fire(task: ScheduledTask) -> None:
    """One scheduled fire. Deliberately NOT arslan._dispatch_spawn — its roster-join /
    routing-announcement side effects are wrong for a headless fire; the plan pins
    RunRecorder + dispatcher.dispatch directly.

    Order matters: the in-flight scheduled_task_runs row is inserted FIRST (it IS the
    single-flight gate), and EVERY exit records an outcome against that exact row
    (S6) — ok advances the cadence, any exception becomes outcome='error' and counts
    toward the 3-fail auto-pause."""
    task_id, name = task.id, task.name
    spawn_id, prompt = task.spawn_id, task.prompt
    cid = task.conversation_id or f"scheduled-{task_id}"
    async with db_session.AsyncSessionLocal() as db:
        row = ScheduledTaskRun(task_id=task_id, started_at=datetime.utcnow())
        db.add(row)
        await db.flush()          # assigns the PK without a post-commit refresh
        row_id = row.id
        await db.commit()

    run_id: int | None = None
    try:
        spawn_name = None if spawn_id is None else await dispatcher.get_spawn_name(spawn_id)
        if spawn_name is None:
            # S8: ondelete SET NULL (spawn deleted) or a dangling id — a clean error
            # outcome that self-heals via the 3-fail auto-pause, never a supervisor
            # crash. Checked BEFORE RunRecorder.start (a dangling spawn_id FK would
            # crash the Run insert).
            raise ValueError("spawn 已删除")
        recorder = await run_recorder.RunRecorder.start(
            conversation_id=cid, spawn_id=spawn_id, spawn_name=spawn_name,
            user_message=prompt, kind="scheduled")
        run_id = recorder.run_id
        await _dispatch_recorded(recorder, cid, spawn_id, prompt)
    except Exception as exc:  # noqa: BLE001 — a failed fire is an error outcome, not a crash
        logger.warning("scheduled task %s fire failed: %s", task_id, exc)
        await record_outcome(task_id, False, row_id=row_id, run_id=run_id,
                             reason=str(exc))
        return

    await record_outcome(task_id, True, row_id=row_id, run_id=run_id)
    # Best-effort timeline entry (log_event never raises) — the recap shows the fire
    # even when nobody was online to see the stream.
    await recap_service.log_event(
        cid, "scheduled_fire", {"task_id": task_id, "run_id": run_id},
        f"定时任务「{name}」已执行")


# ── the loop ─────────────────────────────────────────────────────────────────────────

async def tick() -> None:
    """One scheduler pass: fire every due task (supervised), skip overlapping ones."""
    now = datetime.utcnow()
    for task in await due_tasks(now):
        try:
            if await has_inflight(task.id):
                await record_skip_overlap(task.id)
                continue
            _supervise(_fire(task))
        except Exception as exc:  # noqa: BLE001 — one bad task must not stall the tick
            logger.warning("scheduler tick: task %s failed (non-fatal): %s", task.id, exc)


async def watch_loop(*, interval: float = DEFAULT_INTERVAL,
                     stop_event: asyncio.Event | None = None) -> None:
    """Run ticks forever (until `stop_event`), sleeping `interval` between them.
    Sweeps orphaned in-flight rows ONCE before the first tick (I2) so a crash
    mid-run never wedges a task."""
    try:
        await sweep_orphans()
    except Exception as exc:  # noqa: BLE001 — a failed sweep must not kill the loop
        logger.warning("scheduler orphan sweep failed (non-fatal): %s", exc)
    while stop_event is None or not stop_event.is_set():
        try:
            await tick()
        except Exception as exc:  # noqa: BLE001 — a tick failure must not kill the loop
            logger.warning("scheduler tick failed (non-fatal): %s", exc)
        if stop_event is None:
            await asyncio.sleep(interval)
        else:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass


def start(*, interval: float = DEFAULT_INTERVAL) -> None:
    """Start the supervised scheduler loop (idempotent). Called from the app lifespan."""
    global _loop_task, _stop_event
    if _loop_task is not None and not _loop_task.done():
        return
    _stop_event = asyncio.Event()
    _loop_task = _supervise(watch_loop(interval=interval, stop_event=_stop_event))


async def stop() -> None:
    """Signal the loop to stop and await its exit (best-effort). Called on shutdown."""
    global _loop_task
    if _stop_event is not None:
        _stop_event.set()
    if _loop_task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(_loop_task), timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        _loop_task = None
