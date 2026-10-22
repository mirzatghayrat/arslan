"""Retention heartbeat for `brain_usage_events` (D5), and nothing else.

🔴 This module exists ONLY because `brain_usage_events` needs a bound.
`brain_usage.record` appends one row on every scoped retrieval, unconditionally (the
answer path calls `knowledge.retrieve_scoped` with `record_usage=True`), and an
append-only log with no ceiling is the "只增不减 换张表复活" failure D5's two gates
exist to prevent.

Until v0.1.63 the prune rode on the curation loop's heartbeat
(`curation_loop.prune_usage_events`, the only caller of `brain_usage.prune_events`).
C8-3 deletes that loop, so the prune moved here first, unchanged:
- the same cadence: first pass INITIAL_DELAY after boot, then every DEFAULT_INTERVAL;
- the same settings: `brain_usage_event_retention_days` and
  `brain_usage_event_max_rows`, read fresh on every pass (0 disables a gate, as before);
- the same fail-open behaviour: a failed pass is logged and the next one still runs.

It is maintenance, not a feature, so no opt-in switch gates it. It must run on a
default install.

DELETE-BY: with `brain_usage_events`. The v0.1.65 memory-file card decides whether
that table stays; if it goes, this module goes with it.
"""
from __future__ import annotations

import asyncio
import logging

from server.db import session as db_session
from server.services import brain_usage, settings_service

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 900.0        # 15 min, the curation loop's old heartbeat
INITIAL_DELAY = 300.0           # first pass 5 min after boot, as before

_loop_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


async def prune_usage_events() -> None:
    """One D5 retention pass for brain_usage_events. prune_events is itself fail-open."""
    async with db_session.AsyncSessionLocal() as db:
        days = await settings_service.brain_usage_event_retention_days(db)
        max_rows = await settings_service.brain_usage_event_max_rows(db)
    deleted = await brain_usage.prune_events(retention_days=days, max_rows=max_rows)
    if deleted:
        logger.info("pruned %d brain_usage_events (age>%dd or over %d rows)",
                    deleted, days, max_rows)


async def watch_loop(*, interval: float, initial_delay: float,
                     stop_event: asyncio.Event | None = None) -> None:
    """Prune forever (until `stop_event`), after the initial delay."""
    if initial_delay > 0:
        if stop_event is None:
            await asyncio.sleep(initial_delay)
        else:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=initial_delay)
                return          # stopped during the delay: never prune at all
            except asyncio.TimeoutError:
                pass
    while stop_event is None or not stop_event.is_set():
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


def _on_done(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.warning("usage retention loop failed: %s", task.exception())


def start(*, interval: float | None = None, initial_delay: float | None = None) -> None:
    """Start the retention loop (idempotent). Called from the app lifespan.

    The defaults are read at call time, not bound into the signature, so a boot test can
    shorten the cadence without replacing start() itself."""
    global _loop_task, _stop_event
    if _loop_task is not None and not _loop_task.done():
        return
    _stop_event = asyncio.Event()
    _loop_task = asyncio.create_task(watch_loop(
        interval=DEFAULT_INTERVAL if interval is None else interval,
        initial_delay=INITIAL_DELAY if initial_delay is None else initial_delay,
        stop_event=_stop_event))
    _loop_task.add_done_callback(_on_done)


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
    # A left-behind SET event would make a later start() see a stale stop signal.
    _stop_event = None
