"""D5 retention for brain_usage_events runs on its own loop (C8-3, v0.1.63).

The prune rode on the curation loop's heartbeat until C8-3 deleted that loop.
`brain_usage.record` appends on every retrieval whatever any switch says, so the
prune must run on a default install, with no opt-in. The prune itself (both gates,
batching, fail-open) is tested in test_brain_usage_events.py.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from server.services import usage_retention
from tests.server.test_brain_usage_events import _count, _seed_events


@pytest.fixture
async def usage_db(client, monkeypatch):
    from server.db import session as db_session

    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    return client


async def test_retention_runs_without_any_opt_in(usage_db, monkeypatch):
    """🔴 Tripwire, moved from test_brain_usage_events (it used to drive the curation
    loop's watch_loop with both curation switches off). Retention gated behind an
    opt-in switch would never run on a default install, and the table would grow
    forever: the "只增不减 换张表复活" failure the ceiling exists to prevent.

    So: run the loop and assert the prune happened."""
    await _seed_events(usage_db.db_maker, [
        ("note", "note:1", datetime.utcnow() - timedelta(days=90))])

    stop = asyncio.Event()
    calls: list[int] = []
    real = usage_retention.prune_usage_events

    async def _spy():
        await real()
        calls.append(1)
        stop.set()

    monkeypatch.setattr(usage_retention, "prune_usage_events", _spy)
    await asyncio.wait_for(
        usage_retention.watch_loop(interval=0.01, initial_delay=0, stop_event=stop),
        timeout=5)

    assert calls, "retention must not sit behind an opt-in switch"
    assert await _count(usage_db.db_maker) == 0


async def test_a_failed_pass_does_not_stop_the_next_one(monkeypatch):
    """Fail-open, as on the curation heartbeat: maintenance must not kill the loop."""
    stop = asyncio.Event()
    calls: list[int] = []

    async def _flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("synthetic prune failure")
        stop.set()

    monkeypatch.setattr(usage_retention, "prune_usage_events", _flaky)
    await asyncio.wait_for(
        usage_retention.watch_loop(interval=0.01, initial_delay=0, stop_event=stop),
        timeout=5)
    assert len(calls) == 2


async def test_start_is_idempotent_and_stop_ends_the_loop(monkeypatch):
    async def _noop():
        return None

    monkeypatch.setattr(usage_retention, "prune_usage_events", _noop)
    usage_retention.start(interval=0.01, initial_delay=0.0)
    first = usage_retention._loop_task
    usage_retention.start(interval=0.01, initial_delay=0.0)
    assert usage_retention._loop_task is first, "start() must not spawn a second loop"
    await usage_retention.stop()
    assert usage_retention._loop_task is None
    assert first.done()


async def test_a_default_boot_prunes_old_usage_events(tmp_path, monkeypatch):
    """Drives server.main.lifespan on a fresh install, not a replica of it.

    No settings rows at all, so every opt-in switch (curation included) is at its
    default, off. An event older than the default 30-day window must still be pruned
    while the app runs. If the lifespan stopped starting usage_retention, nothing
    would ever prune and this would fail.
    """
    import importlib

    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from server import crypto

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = tmp_path / "boot.db"
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "a-real-strong-random-key-0123456789")
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ARSLAN_DB_PATH", str(db))
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    import server.config as config

    importlib.reload(config)
    # The boot adopts a salt into process-global crypto state; put it back afterwards.
    monkeypatch.setattr(crypto, "_salt", crypto._salt)
    monkeypatch.setattr(crypto, "_salt_source", crypto._salt_source)

    eng = create_async_engine(f"sqlite+aiosqlite:///{db}")
    maker = async_sessionmaker(eng, expire_on_commit=False)
    import server.db.session as db_session
    import server.main as main

    monkeypatch.setattr(main, "engine", eng)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    # The real cadence (5 min, then 15) is too slow for a test; the loop and its
    # wiring are the real ones.
    monkeypatch.setattr(usage_retention, "INITIAL_DELAY", 0.0)
    monkeypatch.setattr(usage_retention, "DEFAULT_INTERVAL", 0.05)

    try:
        async with main.lifespan(FastAPI()):
            await _seed_events(maker, [
                ("note", "note:1", datetime.utcnow() - timedelta(days=90))])
            deadline = asyncio.get_running_loop().time() + 20
            while await _count(maker) and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.05)
            assert await _count(maker) == 0, "a default boot never pruned brain_usage_events"
    finally:
        await usage_retention.stop()
        await eng.dispose()
