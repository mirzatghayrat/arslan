"""Background evolution job (S2 E5, audit CRITICAL-4).

There is no scheduler in this codebase, so this is a small SUPERVISED watcher built by hand:

- Every attempt runs as an `asyncio.create_task` that is kept in a module-level set with a
  done-callback that LOGS any exception and discards the task — never a bare
  fire-and-forget that would silently swallow a crash.
- `watch_loop()` wakes every `interval` seconds (300s in prod, injectable + driven manually
  in tests) and, for each spawn, checks the trigger. `notify_spawn()` is an in-process ping
  from the run recorder so a freshly scored run doesn't wait up to 5 min; the loop is the
  backstop.

Trigger + deterministic backoff (the thing the sync button could never do):
- A spawn is eligible when the number of NEW replayable epoch>=1 live+scored runs created
  since its LAST EvolutionAttempt reaches a threshold. "Since the last attempt" (not the
  last proposal — audit CRITICAL-4) is what makes a failing gate back off instead of
  retrying every 5 minutes forever: the moment an attempt is recorded, those runs are behind
  it and no longer count.
- Threshold starts at BASE_THRESHOLD (10). After N consecutive failed/error attempts it is
  BASE * 2**N, capped at BASE * MAX_BACKOFF_MULT — i.e. 10 → 20 → 40 → 80. A passed attempt
  resets the streak (back to 10).

Safety rails (spec §4): evolution_auto=on is standing consent, but an attempt still (a)
records a `skipped_budget` attempt instead of running if its lower-bound estimate exceeds
`evolution_max_est_tokens`, and (b) runs at most one attempt per spawn concurrently.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import EvolutionAttempt, EvolutionProposal, Run, Spawn
from server.services import evolution_estimate, evolution_loop, replay_run, settings_service

logger = logging.getLogger(__name__)

BASE_THRESHOLD = 10
MAX_BACKOFF_MULT = 8            # 10 → 20 → 40 → 80 then flat
DEFAULT_INTERVAL = 300.0       # 5 minutes; injectable (short in tests)

# ── supervised task bookkeeping ──────────────────────────────────────────────────────
_tasks: set[asyncio.Task] = set()
_running_spawns: set[int] = set()   # concurrency = 1 per spawn
_loop_task: asyncio.Task | None = None
_started = False                    # notify_spawn is a no-op until the loop is running


def _on_task_done(task: asyncio.Task) -> None:
    _tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("evolution watcher task crashed: %s", exc, exc_info=exc)


def _supervise(coro) -> asyncio.Task:
    """Launch `coro` as a tracked task whose failures are LOGGED, not lost."""
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_on_task_done)
    return task


# ── trigger math ─────────────────────────────────────────────────────────────────────

def _threshold(consecutive_fails: int) -> int:
    """Backoff schedule: BASE * min(2**fails, MAX_BACKOFF_MULT). 10, 20, 40, 80, 80, …"""
    return BASE_THRESHOLD * min(2 ** max(consecutive_fails, 0), MAX_BACKOFF_MULT)


async def _last_attempt_started_at(db, spawn_id: int):
    return (await db.execute(
        select(EvolutionAttempt.started_at)
        .where(EvolutionAttempt.spawn_id == spawn_id)
        .order_by(EvolutionAttempt.id.desc())
        .limit(1)
    )).scalar()


async def _consecutive_fails(db, spawn_id: int) -> int:
    """Trailing run of failed/error attempts (newest → oldest). A 'passed' resets to 0; a
    'skipped_budget' or an in-flight (outcome=None) attempt stops the count (neutral)."""
    outcomes = (await db.execute(
        select(EvolutionAttempt.outcome)
        .where(EvolutionAttempt.spawn_id == spawn_id)
        .order_by(EvolutionAttempt.id.desc())
    )).scalars().all()
    fails = 0
    for outcome in outcomes:
        if outcome in ("failed", "error"):
            fails += 1
        else:
            break
    return fails


async def _new_replayable_run_count(db, spawn_id: int, since) -> int:
    """Number of clean, gateable, hermetically-replayable runs created after `since`
    (all epoch>=1 live scored runs when `since` is None)."""
    q = select(Run).where(
        Run.spawn_id == spawn_id, Run.kind == "live", Run.epoch >= 1,
        Run.status == "scored",
    )
    if since is not None:
        q = q.where(Run.created_at > since)
    runs = (await db.execute(q)).scalars().all()
    count = 0
    for run in runs:
        if await replay_run.is_replayable(db, run.id):
            count += 1
    return count


async def _is_eligible(db, spawn_id: int) -> bool:
    since = await _last_attempt_started_at(db, spawn_id)
    fails = await _consecutive_fails(db, spawn_id)
    count = await _new_replayable_run_count(db, spawn_id, since)
    return count >= _threshold(fails)


# ── one attempt ──────────────────────────────────────────────────────────────────────

async def _create_attempt(db, spawn_id: int) -> tuple[int, dict]:
    """Persist a fresh in-flight attempt row carrying its pre-run estimate; return its id."""
    est = await evolution_estimate.estimate(db, spawn_id)
    attempt = EvolutionAttempt(spawn_id=spawn_id, started_at=datetime.utcnow(),
                               estimate=est, reason="")
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)
    return attempt.id, est


async def _finalize_attempt(attempt_id: int, *, outcome: str, reason: str,
                            proposal_id: int | None = None, actual: dict | None = None) -> None:
    async with db_session.AsyncSessionLocal() as db:
        attempt = await db.get(EvolutionAttempt, attempt_id)
        if attempt is None:
            return
        attempt.outcome = outcome
        attempt.reason = (reason or "")[:2000]
        attempt.proposal_id = proposal_id
        attempt.actual = actual
        attempt.finished_at = datetime.utcnow()
        await db.commit()


async def _perform_attempt(attempt_id: int, spawn_id: int) -> None:
    """Run the estimate/budget/propose flow for a pre-created attempt row and finalize it.

    Budget gate: if a `evolution_max_est_tokens` cap is set and the attempt's lower-bound
    est_tokens exceeds it, record outcome='skipped_budget' and DO NOT run propose_improvement.
    Otherwise run it; outcome = 'passed' if a proposal was written, 'failed' if the gate
    failed, 'error' on exception."""
    async with db_session.AsyncSessionLocal() as db:
        attempt = await db.get(EvolutionAttempt, attempt_id)
        est = dict(attempt.estimate or {}) if attempt else {}
        max_est = await settings_service.evolution_max_est_tokens(db)

    est_tokens = int(est.get("est_tokens") or 0)
    if max_est is not None and est_tokens > max_est:
        await _finalize_attempt(
            attempt_id, outcome="skipped_budget",
            reason=f"estimate {est_tokens} tokens exceeds budget {max_est}")
        return

    try:
        result = await evolution_loop.propose_improvement(spawn_id)
    except Exception as exc:  # noqa: BLE001 — an attempt failure must not crash the watcher
        logger.warning("evolution attempt error (spawn=%s): %s", spawn_id, exc)
        await _finalize_attempt(attempt_id, outcome="error", reason=str(exc))
        return

    proposal_id = result.get("proposal_id")
    if proposal_id is not None:
        await _finalize_attempt(attempt_id, outcome="passed", reason="gate passed",
                                proposal_id=proposal_id)
    else:
        reason = (result.get("gate") or {}).get("reason") or "gate did not pass"
        await _finalize_attempt(attempt_id, outcome="failed", reason=reason)


async def _run_and_release(attempt_id: int, spawn_id: int) -> None:
    try:
        await _perform_attempt(attempt_id, spawn_id)
    finally:
        _running_spawns.discard(spawn_id)


async def enqueue_attempt(spawn_id: int, *, manual: bool = False) -> int | None:
    """Create an attempt row and supervise its runner. Returns the attempt_id, or None when
    an attempt is already running for this spawn (concurrency = 1). This is the ONE entry the
    manual API and the auto trigger share — both respect concurrency + the budget cap; only
    the auto trigger additionally gates on the run-count threshold (see `trigger_spawn`)."""
    if spawn_id in _running_spawns:
        return None
    _running_spawns.add(spawn_id)
    try:
        async with db_session.AsyncSessionLocal() as db:
            attempt_id, _est = await _create_attempt(db, spawn_id)
    except Exception:
        _running_spawns.discard(spawn_id)
        raise
    _supervise(_run_and_release(attempt_id, spawn_id))
    return attempt_id


async def trigger_spawn(spawn_id: int) -> int | None:
    """Auto path: gate on evolution_auto + the run-count/backoff threshold + concurrency,
    then enqueue. Returns the attempt_id if one was started, else None."""
    if spawn_id in _running_spawns:
        return None
    async with db_session.AsyncSessionLocal() as db:
        if not await settings_service.evolution_auto(db):
            return None
        if not await _is_eligible(db, spawn_id):
            return None
    return await enqueue_attempt(spawn_id, manual=False)


# ── living-proposal refresh (wired into the loop) ─────────────────────────────────────

async def _refresh_open_proposals() -> None:
    async with db_session.AsyncSessionLocal() as db:
        open_ids = (await db.execute(
            select(EvolutionProposal.id).where(EvolutionProposal.status == "open")
        )).scalars().all()
    for pid in open_ids:
        try:
            async with db_session.AsyncSessionLocal() as db:
                await evolution_loop.refresh_proposal(db, pid)
        except Exception as exc:  # noqa: BLE001 — one bad proposal must not stall the loop
            logger.warning("refresh_proposal(%s) failed (non-fatal): %s", pid, exc)


# ── the loop ─────────────────────────────────────────────────────────────────────────

async def tick() -> None:
    """One watcher pass: refresh open proposals, then check every spawn's trigger."""
    await _refresh_open_proposals()
    async with db_session.AsyncSessionLocal() as db:
        spawn_ids = (await db.execute(select(Spawn.id))).scalars().all()
    for sid in spawn_ids:
        try:
            await trigger_spawn(sid)
        except Exception as exc:  # noqa: BLE001 — a bad spawn must not stall the loop
            logger.warning("trigger_spawn(%s) failed (non-fatal): %s", sid, exc)


async def watch_loop(*, interval: float = DEFAULT_INTERVAL,
                     stop_event: asyncio.Event | None = None) -> None:
    """Run ticks forever (until `stop_event`), sleeping `interval` between them."""
    while stop_event is None or not stop_event.is_set():
        try:
            await tick()
        except Exception as exc:  # noqa: BLE001 — a tick failure must not kill the loop
            logger.warning("evolution watch tick failed (non-fatal): %s", exc)
        if stop_event is None:
            await asyncio.sleep(interval)
        else:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass


_stop_event: asyncio.Event | None = None


def start(*, interval: float = DEFAULT_INTERVAL) -> None:
    """Start the supervised watch loop (idempotent). Called from the app lifespan."""
    global _loop_task, _stop_event, _started
    if _loop_task is not None and not _loop_task.done():
        return
    _stop_event = asyncio.Event()
    _loop_task = _supervise(watch_loop(interval=interval, stop_event=_stop_event))
    _started = True


async def stop() -> None:
    """Signal the loop to stop and await its exit (best-effort). Called on shutdown."""
    global _loop_task, _started
    _started = False
    if _stop_event is not None:
        _stop_event.set()
    if _loop_task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(_loop_task), timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        _loop_task = None


def notify_spawn(spawn_id: int) -> None:
    """In-process ping from the run recorder that a spawn just got a fresh scored run.

    No-op unless the watch loop is running (the loop is the backstop; a ping only shortens
    latency). Best-effort + non-blocking: schedules a supervised trigger check and returns.
    Requires a running event loop (it always has one — the recorder is async)."""
    if not _started:
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    _supervise(trigger_spawn(spawn_id))
