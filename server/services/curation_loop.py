"""整理层 (curation layer): a sleep-time loop that finishes what the interactive
paths missed, and never silently costs money doing it.

WHY A NEW LOOP. There is no generic job registry in this codebase: `scheduled_tasks`
rows are USER tasks (prompt + spawn_id required, the unit of work is always an LLM
dispatch to a spawn), and every "sweep"/"reaper" elsewhere runs once at boot, not
periodically. The only real pattern is a hand-rolled supervised watch loop — this is
the third one, deliberately shaped like `server/services/scheduler.py` so the three
read alike. It does NOT copy that module's has_inflight single-flight gate, which is a
known TOCTOU.

WHAT IT DOES. Conversations whose `session_ended` never fired (the browser was closed,
the tab crashed, the server restarted) never get distilled: the frontend is the only
emitter of that frame and it is explicitly best-effort. This loop finds those and
distills them.

HONEST COVERAGE. The sweep can only ever cover the `distill_session` path, because
that is the only distillation that writes a `DistilledSession` marker to anti-join
against. The other four trigger paths (dual-track, sandbox merge, direct chat, and
anything else built on `distill_from_signals`) write no marker — and two of them have
no conversation_id at all — so they are structurally invisible here. Do not let any UI
or doc imply this is a complete safety net.

SPEND. MAX_PER_TICK conversations per tick × one LLM call per producing spawn (the
meta-upflow is skipped in propose_only mode). At the default 900s interval that is at
most 5 × 96 = 480 conversation-sweeps/day, typically 1–2 spawns each. The retry cap and
the terminal give-up marker bound the pathological tail; the two kill switches bound
the whole thing at zero.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select

from server.db import session as db_session
from server.db.models import ArslanMessage, ConversationEvent, DistilledSession
from server.services import (
    brain_usage,
    distill_service,
    recap_service,
    settings_service,
)
from server.services.replay_safety import should_not_curate

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 900.0        # 15 min — curation is idle work, not a scheduler
INITIAL_DELAY = 300.0           # a fresh boot must not immediately spend on LLM calls
IDLE_WINDOW_S = 21600           # 6h since the last message ⇒ the session is really over
MAX_PER_TICK = 5                # bound the first-tick historical backfill
MAX_ATTEMPTS = 3                # strikes before a conversation is permanently abandoned
RETRY_COOLDOWN_S = 21600        # 6h between attempts on the same conversation

#: The sweep's OWN failure kind. Deliberately distinct from the user-facing
#: `distill_failed` that interactive paths write: sharing one kind would let a user
#: retrying a manual distill during an outage permanently disqualify the conversation
#: from ever being swept, and would double-count every sweep failure.
FAILED_EVENT_KIND = "curation_failed"
GAVE_UP_REASON = "curation_gave_up"

_loop_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None
_tasks: set[asyncio.Task] = set()

#: Second line of defence for the retry cap. `recap_service.count_events` swallows its
#: own exceptions and returns 0, and under WAL a degraded DB typically FAILS WRITES
#: while reads still succeed — so the DB-backed strike may never persist and the
#: counter would read "zero strikes" forever. This in-process tally survives that shape.
#: It does NOT survive a restart; a crash-looping deployment is uncapped (documented,
#: not papered over — the terminal marker is what makes a real give-up durable).
_attempts: dict[str, int] = {}


def _on_task_done(task: asyncio.Task) -> None:
    _tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning("curation task failed: %s", task.exception())


def _supervise(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_on_task_done)
    return task


async def _enabled() -> bool:
    """BOTH switches, read fresh every tick so a change takes effect without a restart.

    `distill_on_session_end` is the user's existing statement about whether their
    sessions may be distilled at all; a background sweep that ignored it would both
    violate that consent and spend money doing so.
    """
    async with db_session.AsyncSessionLocal() as db:
        if not await settings_service.curation_enabled(db):
            return False
        return await settings_service.distill_enabled(db)


async def _strikes(conversation_id: str) -> int | None:
    """How many times the sweep has already failed on this conversation.

    Returns None when the count is UNKNOWN (a read error). Callers must then skip this
    tick — fail-closed for SPEND — but must NOT treat it as a permanent give-up: a
    transient DB hiccup should cost one tick, not brand the conversation dead forever
    after zero real attempts.
    """
    in_process = _attempts.get(conversation_id, 0)
    try:
        persisted = await recap_service.count_events_strict(
            conversation_id, FAILED_EVENT_KIND)
    except Exception as exc:  # noqa: BLE001 — unknown strike count ⇒ skip, don't spend
        logger.warning("curation: strike count unavailable for %s (%s) — skipping this "
                       "tick so a degraded DB cannot uncap LLM spend",
                       conversation_id, exc.__class__.__name__)
        return None
    return max(in_process, persisted)


async def _recently_failed(conversation_id: str) -> bool:
    cutoff = datetime.utcnow() - timedelta(seconds=RETRY_COOLDOWN_S)
    async with db_session.AsyncSessionLocal() as db:
        row = (await db.execute(select(ConversationEvent.id).where(
            ConversationEvent.conversation_id == conversation_id,
            ConversationEvent.kind == FAILED_EVENT_KIND,
            ConversationEvent.created_at >= cutoff,
        ).limit(1))).scalar_one_or_none()
    return row is not None


async def _give_up(conversation_id: str) -> None:
    """Write the TERMINAL marker for every undistilled pair in this conversation.

    This is what makes the give-up real: the candidate query anti-joins
    `distilled_sessions`, so the pair leaves the candidate set instead of being
    re-selected (and re-charged) every tick — which also stops a handful of dead
    conversations from starving the per-tick budget — and it survives a restart.
    """
    async with db_session.AsyncSessionLocal() as db:
        spawn_ids = (await db.execute(select(ArslanMessage.spawn_id).where(
            ArslanMessage.conversation_id == conversation_id,
            ArslanMessage.role == "spawn_summary",
            ArslanMessage.spawn_id.isnot(None),
        ).distinct())).scalars().all()
        marked = (await db.execute(select(DistilledSession.spawn_id).where(
            DistilledSession.conversation_id == conversation_id))).scalars().all()
        for sid in set(int(s) for s in spawn_ids) - set(int(s) for s in marked):
            db.add(DistilledSession(conversation_id=conversation_id, spawn_id=sid,
                                    reason=GAVE_UP_REASON))
        await db.commit()
    logger.warning(
        "curation: giving up on %s after %d failed attempts — it will not be swept "
        "again (the distill_failed / curation_failed events stay for inspection)",
        conversation_id, MAX_ATTEMPTS)


async def ensure_backfill_boundary() -> None:
    """Record where the sweep's scope starts, the first time curation is found enabled.

    🔴 Without this, flipping `curation_enabled` makes the very next tick a HISTORICAL
    BACKFILL: `_candidates` selects every conversation with an undistilled deliverable
    and no activity for 6h, which at that moment is every such conversation ever
    recorded. MAX_PER_TICK bounds the RATE (5 per 15 min ≈ 480/day), not the total — on
    an install with months of history that is days of continuous LLM spend beginning
    five minutes after the switch.

    So enabling curation means "curate from here on". Reaching back over history is a
    separate explicit act; this round does not add one, and the log says so rather than
    letting the omission look like completeness.

    Written ONCE. Re-recording on every tick would move the boundary forward forever and
    the sweep would never run at all. Not written while curation is OFF — deciding, months
    early, which history is permanently out of scope is not a decision a disabled loop
    gets to make.
    """
    async with db_session.AsyncSessionLocal() as db:
        if not await settings_service.curation_enabled(db):
            # Belt and braces for the settings write path, which is the authoritative
            # place this is cleared: a boundary can also arrive from a direct DB edit or
            # a build that predates that clearing, and a stale one would silently
            # backfill the whole off-period on the next enable.
            if await settings_service.curation_backfill_from(db) is not None:
                await settings_service.clear_curation_backfill_from(db)
                logger.info("curation: disabled — backfill boundary cleared; enabling "
                            "again will start a fresh scope rather than sweeping the gap")
            return
        if await settings_service.curation_backfill_from(db) is not None:
            return
        now = datetime.utcnow()
        await settings_service.set_curation_backfill_from(db, now)
    logger.info(
        "curation: scope starts %s — conversations idle before that are NOT swept. "
        "Distilling existing history is a separate action this build does not offer.",
        now.isoformat())


async def _candidates() -> list[str]:
    """Conversations with an undistilled spawn deliverable and no recent activity.

    The idle signal is MAX(ArslanMessage.timestamp) — the conversation's own last
    message. ConversationEvent is NOT usable: the canonical target of this sweep (user
    @-mentions an already-rostered spawn, the spawn answers, the tab closes) writes no
    event at all, and events cluster at the START of a conversation, so a still-live
    session would read as idle and get distilled early — writing a marker that
    permanently suppresses the real end-of-session distillation.
    """
    cutoff = datetime.utcnow() - timedelta(seconds=IDLE_WINDOW_S)
    marked = select(DistilledSession.conversation_id).where(
        DistilledSession.spawn_id == ArslanMessage.spawn_id,
        DistilledSession.conversation_id == ArslanMessage.conversation_id,
    ).exists()
    # 🔴 Idleness is a property of the CONVERSATION, so it must be computed over ALL of
    # its messages — a correlated subquery, not the outer aggregate. The candidate
    # filters (spawn_summary / unmarked) are a WHERE clause and therefore apply BEFORE
    # the GROUP BY: aggregating over the filtered rows measured only "when did the last
    # UNDISTILLED spawn deliverable arrive", so a conversation the user was still using
    # all day looked idle the moment its morning deliverable aged out. Sweeping it early
    # writes a NORMAL marker, which permanently suppresses the real end-of-session
    # distillation and also blocks the manual retry (that path only ignores a give-up
    # marker) — silent, unrecoverable loss of the whole session's material.
    inner = ArslanMessage.__table__.alias("m_all")
    last_activity = (
        select(func.max(inner.c.timestamp))
        .where(inner.c.conversation_id == ArslanMessage.conversation_id)
        .scalar_subquery()
    )
    async with db_session.AsyncSessionLocal() as db:
        # The backfill boundary. Absent (or unparsable) means "no scope recorded yet",
        # and the fail-closed reading of that is to sweep NOTHING — ensure_backfill_boundary
        # records one on the next tick. Falling through to "no gate" would silently
        # reopen the whole historical backfill.
        floor = await settings_service.curation_backfill_from(db)
        if floor is None:
            return []
        rows = (await db.execute(
            select(ArslanMessage.conversation_id)
            .where(
                ArslanMessage.role == "spawn_summary",
                ArslanMessage.spawn_id.isnot(None),
                ~marked,
                last_activity < cutoff,
                last_activity >= floor,
            )
            .group_by(ArslanMessage.conversation_id)
        )).scalars().all()
    return [cid for cid in rows if not should_not_curate(cid)]


async def _sweep_once(conversation_id: str) -> None:
    """Distill one conversation, and account for the attempt.

    A strike is written on ANY non-success — including an exception — because the cap
    counts strikes: a failure shape that produced no event would retry forever, which
    is exactly the unbounded LLM burn this cap exists to prevent.
    """
    ok = False
    reason = "unknown"
    try:
        report = await distill_service.distill_session_detailed(
            conversation_id, propose_only=True, usage_scope="curation_distill")
        ok = report.distilled > 0
        if not ok:
            # the first FAILING reason — reasons[0] would report a benign
            # 'already_distilled' skip as if it were the cause of the failure
            failing = [o.reason for o in report.outcomes if o.failed]
            other = [o.reason for o in report.outcomes if o.reason]
            reason = (failing or other or ["nothing_distilled"])[0]
    except Exception as exc:  # noqa: BLE001 — an exception is a failed attempt, not a free one
        logger.warning("curation sweep of %s raised: %s", conversation_id, exc)
        reason = "exception"

    if ok:
        _attempts.pop(conversation_id, None)
        return

    _attempts[conversation_id] = _attempts.get(conversation_id, 0) + 1
    await recap_service.log_event(
        conversation_id, FAILED_EVENT_KIND, {"reason": reason},
        f"后台整理失败({reason})")
    strikes = await _strikes(conversation_id)
    if strikes is not None and strikes >= MAX_ATTEMPTS:
        await _give_up(conversation_id)


async def tick(stop_event: asyncio.Event | None = None) -> None:
    """One curation pass. Never raises.

    The stop signal is a PARAMETER, not module state: a module-level event stays SET
    after stop(), which would make every later direct tick() a silent no-op — a trap
    for both callers and tests.
    """
    if not await _enabled():
        return
    swept = 0
    for conversation_id in await _candidates():
        if swept >= MAX_PER_TICK:
            break
        if stop_event is not None and stop_event.is_set():
            return
        # Re-read the switches between candidates: a stampede must be interruptible,
        # not only stoppable between ticks.
        if not await _enabled():
            return
        # Cooling / capped conversations are skipped WITHOUT consuming a slot, so a
        # handful of dead ones can never starve the fresh ones.
        if await _recently_failed(conversation_id):
            continue
        strikes = await _strikes(conversation_id)
        if strikes is None:
            continue            # unknown ⇒ skip this tick, but never a terminal give-up
        if strikes >= MAX_ATTEMPTS:
            await _give_up(conversation_id)
            continue
        await _sweep_once(conversation_id)
        swept += 1


async def prune_usage_events() -> None:
    """D5 retention heartbeat for brain_usage_events.

    🔴 It lives HERE, in the while body, and deliberately NOT inside `tick()`.
    `tick()` opens with the opt-in `_enabled()` gate (curation_enabled AND
    distill_on_session_end), both of which default OFF — but `brain_usage.record`
    appends events UNCONDITIONALLY on every retrieval. Retention gated behind an
    opt-in switch would therefore never run on a default install, and the table would
    grow forever: the exact "只增不减 换张表复活" failure the ceiling exists to
    prevent. Retention is maintenance, not a feature; it is not opt-in.

    This loop is the only always-running periodic heartbeat in the repo (the scheduler
    runs user tasks; run_redact is boot-once), which is why the hook is here rather
    than in a new loop of its own. Own try/except at the call site so a prune failure
    cannot cost a curation tick, and prune_events is itself fail-open.
    """
    async with db_session.AsyncSessionLocal() as db:
        days = await settings_service.brain_usage_event_retention_days(db)
        max_rows = await settings_service.brain_usage_event_max_rows(db)
    deleted = await brain_usage.prune_events(retention_days=days, max_rows=max_rows)
    if deleted:
        logger.info("pruned %d brain_usage_events (age>%dd or over %d rows)",
                    deleted, days, max_rows)


async def watch_loop(*, interval: float = DEFAULT_INTERVAL,
                     initial_delay: float = INITIAL_DELAY,
                     stop_event: asyncio.Event | None = None) -> None:
    """Tick forever (until `stop_event`), after an initial delay so a fresh boot never
    immediately spends on LLM calls."""
    if initial_delay > 0:
        if stop_event is None:
            await asyncio.sleep(initial_delay)
        else:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=initial_delay)
                return          # stopped during the delay: never tick at all
            except asyncio.TimeoutError:
                pass
    while stop_event is None or not stop_event.is_set():
        try:
            await ensure_backfill_boundary()
            await tick(stop_event)
        except Exception as exc:  # noqa: BLE001 — a tick failure must not kill the loop
            logger.warning("curation tick failed (non-fatal): %s", exc)
        try:
            await prune_usage_events()
        except Exception as exc:  # noqa: BLE001 — maintenance must not kill the loop
            logger.warning("usage-event prune failed (non-fatal): %s", exc)
        if stop_event is None:
            await asyncio.sleep(interval)
        else:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass


def start(*, interval: float = DEFAULT_INTERVAL,
          initial_delay: float = INITIAL_DELAY) -> None:
    """Start the supervised curation loop (idempotent). Called from the app lifespan."""
    global _loop_task, _stop_event
    if _loop_task is not None and not _loop_task.done():
        return
    _stop_event = asyncio.Event()
    _loop_task = _supervise(
        watch_loop(interval=interval, initial_delay=initial_delay, stop_event=_stop_event))


async def stop() -> None:
    """Signal the loop to stop and await its exit (best-effort)."""
    global _loop_task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _loop_task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(_loop_task), timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        _loop_task = None
    # Clear it: a left-behind SET event would make a later start() (or any direct
    # tick(stop_event=...)) see a stop signal that no longer means anything.
    _stop_event = None
