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
`evolution_max_dispatches`, and (b) runs at most one attempt per spawn concurrently.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from server.db import session as db_session
from arslan.llm import usage_sink
from server.db.models import EvolutionAttempt, EvolutionProposal, Run, Spawn
from server.services import (
    evolution_estimate,
    evolution_loop,
    evolution_meter,
    replay_run,
    settings_service,
)

logger = logging.getLogger(__name__)

BASE_THRESHOLD = 10
MAX_BACKOFF_MULT = 8            # 10 → 20 → 40 → 80 then flat
DEFAULT_INTERVAL = 300.0       # 5 minutes; injectable (short in tests)

# 0036 companion to the cursor change. Because `skipped_budget` no longer advances the
# cursor (it consumed nothing, so it must not strand the banked runs), an over-budget
# spawn would otherwise stay eligible forever and write one refusal row every tick —
# zero LLM cost, but unbounded row growth.
#
# The wall is a COOLDOWN and deliberately NOT a term in the eligibility gate. Refusing
# inside the gate would create no attempt row at all, and `_verdict_code`'s
# skipped_budget branch keys on a row existing — the eligibility panel would fall through
# to "eligible_looking" ("Nothing blocks") while auto evolution was permanently dead.
# Writing the row and rate-limiting it keeps the refusal VISIBLE, which is the whole
# point of recording an attempt for a skip.
#
# 6 HOURS, chosen so the derived daily ceiling is legible rather than incidental:
#   86400 / BUDGET_REFUSAL_COOLDOWN_S = at most 4 refusal rows per spawn per day.
# That is the number to reason about when changing this constant — it is the actual
# bound on the growth this cooldown exists to cap, and it is pinned by
# test_over_budget_spawn_cannot_exceed_the_daily_refusal_ceiling.
BUDGET_REFUSAL_COOLDOWN_S = 6 * 3600

#: The bound the cooldown actually buys, stated once so tests and humans agree on it.
MAX_BUDGET_REFUSALS_PER_DAY = 86_400 // BUDGET_REFUSAL_COOLDOWN_S

# E9-b: gate/pre-gate reasons that are CONSTRUCTION/precondition failures, not quality
# verdicts — they say nothing about the spawn's prompt, so they must NOT drive the
# exponential backoff. Recorded as outcome='skipped_structural' (transparent to the streak).
# "insufficient scored runs" is the pre-gate not-enough-material precondition (evolution_loop
# emits it before the gate runs) — the same construction class as insufficient_holdout, so it
# is transparent too (user-confirmed 2026-07-13). Genuine quality reasons (no-beat /
# holdout_winrate / dim_regressed / real_floor / verbose_fail) are NOT here — they still back off.
STRUCTURAL_REASONS = frozenset({"length_cap", "insufficient_holdout", "insufficient scored runs"})


def _is_structural(reason: str) -> bool:
    return (reason or "").strip() in STRUCTURAL_REASONS

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
    """The cursor: runs created before this are already "behind" an attempt.

    `skipped_budget` is EXCLUDED because it provably consumed nothing — _perform_attempt
    returns at the budget check BEFORE propose_improvement runs. Letting it advance the
    cursor strands every run banked so far: they fall behind it permanently, so raising
    the cap later does not bring them back and the spawn must re-earn a whole threshold.

    Every other outcome — including `error`, and including an IN-FLIGHT attempt
    (outcome IS NULL) — still holds the cursor. That is deliberate: it is the anti-spin
    property C4 depends on (a spawn whose adapter is dead would otherwise retry every
    tick with no backoff, since `error` is also transparent to the fail streak).

    🔴 NULL-safety: written as `IS NOT 'skipped_budget'`, never `!= 'skipped_budget'`,
    which evaluates to NULL — not TRUE — for an in-flight row and would silently drop the
    running attempt from the cursor, letting a second one queue against the same corpus.
    """
    return (await db.execute(
        select(EvolutionAttempt.started_at)
        .where(EvolutionAttempt.spawn_id == spawn_id,
               EvolutionAttempt.outcome.is_distinct_from("skipped_budget"))
        .order_by(EvolutionAttempt.id.desc())
        .limit(1)
    )).scalar()


async def _consecutive_fails(db, spawn_id: int) -> int:
    """Trailing run of genuine-QUALITY 'failed' attempts (newest → oldest). A 'passed' resets to
    0; a 'skipped_budget' or an in-flight (outcome=None) attempt stops the count (neutral). Both a
    'skipped_structural' (E9-b construction/precondition fail) AND an 'error' (an infra/adapter
    failure surfaced by the loop, or a crash) are TRANSPARENT — the scan continues past them, so
    they neither count toward the streak nor reset it. A dead judge adapter must not inflate the
    quality backoff threshold as if the spawn's prompt were un-improvable.

    MANUAL attempts (0036): a manual 'passed' resets the streak like any pass; every
    other manual outcome is transparent. A human's click is not evidence about the
    prompt, so it must neither inflate the threshold nor collapse it."""
    rows = (await db.execute(
        select(EvolutionAttempt.outcome, EvolutionAttempt.source)
        .where(EvolutionAttempt.spawn_id == spawn_id)
        .order_by(EvolutionAttempt.id.desc())
    )).all()
    fails = 0
    for outcome, source in rows:
        # 0036 — manual attempts are handled BY OUTCOME, because "wall" and "filtered"
        # are both wrong and each is wrong in the opposite direction:
        #
        #   * filtering every manual row out (my first design) would strip a manual
        #     'passed' of its power to reset the streak. A manual pass is the user's ONLY
        #     escape from the 80 ceiling — reaching an auto pass first requires
        #     satisfying the very threshold that is stuck high. Plan review caught it.
        #   * walling on every manual row (my second design) is worse: it makes a manual
        #     FAILURE *reset* an accumulated auto streak, so one impatient losing click
        #     drops the threshold 80 -> 10 and multiplies the auto loop's spend rate by
        #     eight. With no budget cap set, this backoff is the only spend brake there
        #     is. Final review caught that one.
        #
        # So: a manual 'passed' BREAKS (reset preserved); any other manual outcome is
        # TRANSPARENT — it neither counts nor resets, exactly like 'error' and
        # 'skipped_structural', and for the same reason: it is not evidence about the
        # prompt in either direction.
        if source == "manual":
            if outcome == "passed":
                break
            continue
        if outcome == "failed":
            fails += 1
        elif outcome in ("skipped_structural", "error"):
            continue  # non-quality (structural precondition / infra-or-crash) — transparent
        else:
            break     # 'passed' / 'skipped_budget' / in-flight (None) stop the streak
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

async def _create_attempt(db, spawn_id: int, *, source: str) -> tuple[int, dict]:
    """Persist a fresh in-flight attempt row carrying its pre-run estimate; return its id.

    `source` is 'auto' or 'manual' and is REQUIRED — it is the thing that makes the
    long-dead `manual` parameter real. NULL is reserved for rows that predate 0036.
    """
    est = await evolution_estimate.estimate(db, spawn_id)
    attempt = EvolutionAttempt(spawn_id=spawn_id, started_at=datetime.utcnow(),
                               estimate=est, reason="", source=source)
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
    """Claim the hermetic fetch allowance for the length of this attempt.

    🔴 This wrapper exists because the previous code reset the allowance
    UNCONDITIONALLY here, and `_running_spawns` allows one attempt per SPAWN,
    not one overall. Attempt B starting refunded attempt A mid-flight: measured
    at 90 spent against a cap of 50 from a single overlap, N x 50 for N — the
    gate loosening exactly when evolution activity, and so spend, is highest.

    `begin` refreshes only when nothing else is in flight, so overlapping
    attempts SHARE one allowance. That is what `_hermetic_fetches`'s own comment
    has always promised ("can only refuse earlier ... never later") and what the
    unconditional reset quietly broke. `finally` matters: an attempt that raises
    must not leave the claim held, or the allowance never refreshes again.
    """
    from server.orchestrator import tool_loop as _tool_loop

    _tool_loop.begin_hermetic_attempt()
    try:
        await _perform_attempt_inner(attempt_id, spawn_id)
    finally:
        _tool_loop.end_hermetic_attempt()


async def _perform_attempt_inner(attempt_id: int, spawn_id: int) -> None:
    """Run the estimate/budget/propose flow for a pre-created attempt row and finalize it.

    Budget gate: if an `evolution_max_dispatches` cap is set and the attempt's DERIVED
    dispatch ceiling exceeds it, record outcome='skipped_budget' and DO NOT run
    propose_improvement. The cap counts dispatches, not tokens: the token estimate
    over-states 3.7-5.2x, so a cap set from real spend would refuse every attempt — the
    gate would fail in the direction where setting a limit turns the feature off.
    Otherwise run it; outcome = 'passed' if a proposal was written, 'failed' if the gate
    failed, 'error' on exception."""
    async with db_session.AsyncSessionLocal() as db:
        attempt = await db.get(EvolutionAttempt, attempt_id)
        est = dict(attempt.estimate or {}) if attempt else {}
        max_dispatches = await settings_service.evolution_max_dispatches(db)

    # 🔴 Two states that must not merge. `basis: "max"` is emitted only by the current
    # estimator, so its absence means the row predates this schema — letting it through is
    # what would have happened yesterday, and the queue really does span deployments (the
    # estimate is written at ENQUEUE time). Its PRESENCE without dispatches_max is
    # structural damage, and a spend gate that shrugs at that fails OPEN. Reading it as
    # `int(... or 0)` would collapse both into "0, never exceeds" — the previous gate's
    # exact defect, wearing a different field.
    if max_dispatches is not None and est.get("basis") == "max":
        projected = est.get("dispatches_max")
        if projected is None:
            await _finalize_attempt(
                attempt_id, outcome="skipped_structural",
                reason="estimate claims basis=max but carries no dispatches_max")
            return
        if int(projected) > max_dispatches:
            await _finalize_attempt(
                attempt_id, outcome="skipped_budget",
                reason=f"projected {int(projected)} dispatches exceeds cap {max_dispatches}")
            return

    # ── real-spend accounting (see _build_actual) ────────────────────────────────
    # Two collectors, deliberately non-overlapping:
    #   usage_sink.collecting()      catches the DIRECT adapter calls — judge, optimizer,
    #                                synthetic generation. Replay dispatches open their
    #                                OWN nested collecting() inside the dispatcher, and a
    #                                nested one shadows this bucket completely, so their
    #                                tokens do NOT land here and cannot be double counted.
    #   replay_run.collect_run_ids() catches the run_ids of exactly the replays THIS task
    #                                dispatched, so their tokens can be summed from the
    #                                Run rows they already live on — by identity, never by
    #                                a spawn_id/time-window join that would absorb
    #                                skill_forge's concurrent replays for the same spawn.
    # Both wrap the try, so an attempt that dies mid-flight still reports what it burned.
    result: dict | None = None
    failure: Exception | None = None
    with usage_sink.collecting(), replay_run.collect_run_ids() as run_ids, \
            evolution_meter.counting():
        try:
            result = await evolution_loop.propose_improvement(spawn_id)
        except Exception as exc:  # noqa: BLE001 — a failure must not crash the watcher
            failure = exc
        direct_tokens = usage_sink.total()
        # `detail()` carries a STICKY per-bucket `estimated` flag: it goes True the
        # moment any adapter reported without a real usage frame. There is no
        # was_estimated() helper — read the buckets. (I nearly called an invented one.)
        direct_estimated = any(b["estimated"] for b in usage_sink.detail()["buckets"])
        counters = evolution_meter.snapshot()

    actual = await _build_actual(direct_tokens, direct_estimated, run_ids, counters)

    if failure is not None:
        logger.warning("evolution attempt error (spawn=%s): %s", spawn_id, failure)
        await _finalize_attempt(attempt_id, outcome="error", reason=str(failure),
                                actual=actual)
        return

    assert result is not None
    proposal_id = result.get("proposal_id")
    if proposal_id is not None:
        await _finalize_attempt(attempt_id, outcome="passed", reason="gate passed",
                                proposal_id=proposal_id, actual=actual)
    else:
        reason = (result.get("gate") or {}).get("reason") or "gate did not pass"
        outcome = "skipped_structural" if _is_structural(reason) else "failed"
        await _finalize_attempt(attempt_id, outcome=outcome, reason=reason, actual=actual)


async def _build_actual(direct_tokens: int, direct_estimated: bool,
                        run_ids: list[int], counters: dict | None) -> dict:
    """Measured cost of one attempt, in the SAME BASIS as `estimate`.

    🔴 est_tokens is the TOTAL — dispatch + direct — because the estimate's own
    est_tokens is `avg_run * dispatches + AVG_JUDGE_TOKENS * judge_calls` and is
    DOMINATED by the dispatch term. An actual holding only the direct half would render
    beside it (PromotionCard reads the same key name on both) as roughly an order of
    magnitude cheaper, for reasons that have nothing to do with reality. The split is
    reported alongside so nobody has to infer it.

    🔴 `estimated` is not decoration. A replay Run's task_tokens is itself the adapter's
    own character-heuristic estimate whenever the provider returned no usage block, and
    the direct half falls back the same way. Calling a number "actual" while it may be a
    guess is precisely the overclaim this work exists to end, so the payload says which
    it is.
    """
    dispatch_tokens = 0
    estimated = direct_estimated
    if run_ids:
        async with db_session.AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(Run.task_tokens, Run.tokens_estimated).where(Run.id.in_(run_ids))
            )).all()
        for tokens, was_est in rows:
            dispatch_tokens += int(tokens or 0)
            estimated = estimated or bool(was_est)

    counters = counters or {}
    failed = counters.get("failed_dispatches", 0)
    return {
        "pairs": counters.get("pairs"),
        # one per replay DISPATCHED, successful or not — the dispatcher notes the id on
        # its failure branch too, because finalize() has already written that run's
        # tokens by then.
        "dispatches": len(run_ids),
        "judge_calls": counters.get("judge_calls"),
        "optimizer_calls": counters.get("optimizer_calls"),
        "synth_calls": counters.get("synth_calls"),
        "dispatch_tokens": dispatch_tokens,
        "direct_tokens": direct_tokens,
        "est_tokens": dispatch_tokens + direct_tokens,
        "failed_dispatches": failed,
        # A dispatch that died before reporting usage contributes 0, so the counts can be
        # short even though every id was collected. Say so rather than presenting a
        # knowingly-incomplete number as a measurement.
        "estimated": estimated or failed > 0,
    }


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
            attempt_id, _est = await _create_attempt(
                db, spawn_id, source="manual" if manual else "auto")
    except Exception:
        _running_spawns.discard(spawn_id)
        raise
    _supervise(_run_and_release(attempt_id, spawn_id))
    return attempt_id


async def _in_budget_refusal_cooldown(db, spawn_id: int) -> bool:
    """True when the newest attempt is a budget refusal younger than the cooldown.

    Only the AUTO path consults this: a human who clicks Evolve is entitled to a fresh,
    visible refusal on demand.
    """
    row = (await db.execute(
        select(EvolutionAttempt.outcome, EvolutionAttempt.started_at)
        .where(EvolutionAttempt.spawn_id == spawn_id)
        .order_by(EvolutionAttempt.id.desc())
        .limit(1)
    )).first()
    if row is None or row[0] != "skipped_budget" or row[1] is None:
        return False
    return (datetime.utcnow() - row[1]).total_seconds() < BUDGET_REFUSAL_COOLDOWN_S


async def trigger_spawn(spawn_id: int) -> int | None:
    """Auto path: gate on evolution_auto + the run-count/backoff threshold + concurrency,
    then enqueue. Returns the attempt_id if one was started, else None."""
    if spawn_id in _running_spawns:
        return None
    async with db_session.AsyncSessionLocal() as db:
        if not await settings_service.evolution_auto(db):
            return None
        if await _in_budget_refusal_cooldown(db, spawn_id):
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
