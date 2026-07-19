"""整理层#10 段 B: the sleep-time curation loop + fallback distillation sweep.

Contract under test:
  - start()/stop() are idempotent and a tick failure never kills the loop; the first
    tick waits INITIAL_DELAY so a fresh boot cannot immediately spend on LLM calls;
  - BOTH kill switches must be on: curation_enabled AND distill_on_session_end. A user
    who turned session-end distillation off must not get background distillation that
    also costs money;
  - the sweep finds conversations whose session_ended never fired (the browser was
    closed) using MAX(ArslanMessage.timestamp) as the idle signal — ConversationEvent
    is NOT usable here: the canonical target (user @-mentions an already-rostered
    spawn, spawn answers, tab closed) writes no event at all, and events cluster at the
    START of a conversation so a live session would read as idle;
  - synthetic eval traffic is never swept (should_not_curate);
  - RETRY CAP (the expensive one): the sweep is the SINGLE writer of `curation_failed`
    and writes one on ANY non-success — including the exception path — so no failure
    shape escapes the counter. After MAX_ATTEMPTS it writes a terminal
    reason='curation_gave_up' marker, which removes the pair from the anti-join so a
    permanently-failing conversation stops costing money AND stops starving the
    per-tick budget. Interactive failures use a DIFFERENT event kind and never consume
    the sweep's budget;
  - a give-up marker must NOT silence the user's manual retry.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import (
    ArslanMessage,
    Base,
    ConversationEvent,
    DistilledSession,
    Setting,
    Spawn,
)
from server.services import curation_loop, distill_service


@pytest.fixture
async def wdb(tmp_path, monkeypatch):
    """File-backed (not :memory:+StaticPool): supervised work runs concurrently with
    its own sessions, which a shared connection would interleave."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'c.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    curation_loop._attempts.clear()
    yield Session
    for t in list(curation_loop._tasks):
        t.cancel()
    curation_loop._tasks.clear()
    # Module-level state leaks across tests exactly like the scheduler's _tasks set:
    # a stale in-process strike count would make later tests see an at-cap conversation.
    curation_loop._attempts.clear()
    await engine.dispose()


async def _enable(Session, *, backfill_days_ago: int = 365):
    """The sweep is OPT-IN (it spends), so every test that expects it to run must turn
    it on explicitly.

    It also needs a BACKFILL BOUNDARY. Enabling curation now means "curate from here on":
    without a boundary the candidate query returns nothing, because the first tick after
    a real flip would otherwise sweep every conversation ever recorded (~480 LLM calls a
    day for days on an install with history). These tests seed conversations aged in
    HOURS, so the boundary is placed a year back — far enough to be out of the way, while
    still exercising the same code path production uses.
    """
    await _set(Session, "curation_enabled", "true")
    await _set(Session, "curation_backfill_from",
               (datetime.utcnow() - timedelta(days=backfill_days_ago)).isoformat())


async def _seed(Session, *, conversation_id="c1", spawn_id=1, age_hours=48):
    """A conversation with a spawn deliverable whose last message is `age_hours` old."""
    old = datetime.utcnow() - timedelta(hours=age_hours)
    async with Session() as db:
        if await db.get(Spawn, spawn_id) is None:
            db.add(Spawn(id=spawn_id, name=f"S{spawn_id}", domain_category="general",
                         system_prompt="sp", memory_facts=[]))
        db.add(ArslanMessage(conversation_id=conversation_id, role="user",
                             content="做个报告", timestamp=old))
        db.add(ArslanMessage(conversation_id=conversation_id, role="spawn_summary",
                             content="报告", display_content="报告", spawn_id=spawn_id,
                             timestamp=old))
        await db.commit()


async def _set(Session, key, value):
    async with Session() as db:
        db.add(Setting(key=key, value=value))
        await db.commit()


async def _events(Session, conversation_id, kind):
    async with Session() as db:
        return (await db.execute(select(ConversationEvent).where(
            ConversationEvent.conversation_id == conversation_id,
            ConversationEvent.kind == kind))).scalars().all()


# --------------------------------------------------------------------------- loop


async def test_start_is_idempotent_and_stop_really_stops(wdb):
    curation_loop.start(interval=0.01, initial_delay=0.0)
    first = curation_loop._loop_task
    curation_loop.start(interval=0.01, initial_delay=0.0)
    assert curation_loop._loop_task is first, "start() must not spawn a second loop"
    await curation_loop.stop()
    assert curation_loop._loop_task is None


async def test_tick_failure_does_not_kill_the_loop(wdb, monkeypatch):
    calls = {"n": 0}

    async def _boom(stop_event=None):
        calls["n"] += 1
        raise RuntimeError("tick exploded")

    monkeypatch.setattr(curation_loop, "tick", _boom)
    curation_loop.start(interval=0.01, initial_delay=0.0)
    await asyncio.sleep(0.06)
    await curation_loop.stop()
    assert calls["n"] >= 2, "the loop must survive a failing tick and keep ticking"


async def test_first_tick_waits_for_the_initial_delay(wdb, monkeypatch):
    """A fresh boot must not immediately fire LLM-spending work."""
    ticked = asyncio.Event()

    async def _tick(stop_event=None):
        ticked.set()

    monkeypatch.setattr(curation_loop, "tick", _tick)
    curation_loop.start(interval=0.01, initial_delay=5.0)
    await asyncio.sleep(0.05)
    assert not ticked.is_set(), "the loop ticked before INITIAL_DELAY elapsed"
    await curation_loop.stop()


# --------------------------------------------------------------------------- consent


async def test_both_kill_switches_must_be_on(wdb, monkeypatch):
    """curation_enabled AND distill_on_session_end. Turning session-end distillation
    off is the user saying 'do not distill my sessions' — the background sweep must not
    quietly do it anyway (and spend money doing so)."""
    swept = []
    monkeypatch.setattr(curation_loop, "_sweep_once",
                        lambda *a, **k: swept.append(1) or _aw(None))
    await _seed(wdb)
    await _enable(wdb)

    await _set(wdb, "distill_on_session_end", "false")
    await curation_loop.tick()
    assert swept == [], "distill kill switch off ⇒ no background distillation"

    async with wdb() as db:
        for row in (await db.execute(select(Setting))).scalars().all():
            await db.delete(row)
        await db.commit()
    await _set(wdb, "curation_enabled", "false")
    await curation_loop.tick()
    assert swept == [], "curation kill switch off ⇒ no sweep"


# --------------------------------------------------------------------------- sweep


async def test_sweep_distills_a_conversation_whose_session_ended_never_fired(wdb, monkeypatch):
    async def _facts(existing, signals):
        return ["用户偏好简短"]
    monkeypatch.setattr(distill_service, "distill_facts", _facts)
    await _seed(wdb)
    await _enable(wdb)

    await curation_loop.tick()

    async with wdb() as db:
        marks = (await db.execute(select(DistilledSession).where(
            DistilledSession.conversation_id == "c1"))).scalars().all()
    # the sweep PROPOSES; nothing reached memory, so the marker says so
    assert len(marks) == 1 and marks[0].reason == "curation_proposed"


async def test_live_conversation_is_not_swept(wdb, monkeypatch):
    """The idle signal is the LAST MESSAGE, so a conversation still being used is not
    distilled early (which would write a marker and permanently suppress the real
    end-of-session distillation)."""
    calls = []
    monkeypatch.setattr(distill_service, "distill_facts",
                        lambda e, s: calls.append(1) or _aw(["x"]))
    await _seed(wdb, conversation_id="live", age_hours=0)
    await _enable(wdb)

    await curation_loop.tick()
    assert calls == []


async def test_synthetic_eval_traffic_is_never_swept(wdb, monkeypatch):
    calls = []
    monkeypatch.setattr(distill_service, "distill_facts",
                        lambda e, s: calls.append(1) or _aw(["x"]))
    await _seed(wdb, conversation_id="evolution-replay")
    await _enable(wdb)

    await curation_loop.tick()
    assert calls == []


# --------------------------------------------------------------------------- retry cap


async def test_every_failure_shape_writes_exactly_one_strike(wdb, monkeypatch):
    """The cap counts curation_failed events, so ANY failure that produced no event
    would retry forever. The sweep writes one per attempt on any non-success —
    including the exception path — and is the ONLY writer of that kind."""
    await _seed(wdb)
    await _enable(wdb)

    async def _fail(existing, signals):
        return None
    monkeypatch.setattr(distill_service, "distill_facts", _fail)
    await curation_loop.tick()
    assert len(await _events(wdb, "c1", "curation_failed")) == 1

    async def _raise(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(distill_service, "distill_session_detailed", _raise)
    await curation_loop._sweep_once("c1")
    assert len(await _events(wdb, "c1", "curation_failed")) == 2, (
        "an exception must also leave a strike, or the burn never stops")


async def test_gives_up_after_max_attempts_and_stops_being_a_candidate(wdb, monkeypatch):
    """The user's nail: a permanently-failing conversation must stop costing money.
    Give-up is TERMINAL via a real marker row, so it also survives a restart and stops
    consuming the per-tick budget."""
    await _seed(wdb)
    await _enable(wdb)
    attempts = []

    async def _fail(existing, signals):
        attempts.append(1)
        return None
    monkeypatch.setattr(distill_service, "distill_facts", _fail)
    # Isolate the CAP from the COOLDOWN (tested separately below): without this the
    # 6h cooldown — correct behaviour — would block attempts 2 and 3 in this loop.
    monkeypatch.setattr(curation_loop, "RETRY_COOLDOWN_S", 0)

    for _ in range(curation_loop.MAX_ATTEMPTS + 2):
        await curation_loop.tick()

    assert len(attempts) == curation_loop.MAX_ATTEMPTS, (
        f"expected exactly {curation_loop.MAX_ATTEMPTS} attempts, got {len(attempts)}")
    async with wdb() as db:
        marks = (await db.execute(select(DistilledSession).where(
            DistilledSession.conversation_id == "c1"))).scalars().all()
    assert [m.reason for m in marks] == ["curation_gave_up"]


async def test_interactive_failures_do_not_consume_the_sweep_budget(wdb, monkeypatch):
    """distill_failed (user-facing) and curation_failed (sweep budget) are different
    kinds on purpose: a user retrying a manual distill during an outage must not
    disqualify the conversation from ever being swept."""
    await _seed(wdb)
    await _enable(wdb)

    async def _fail(existing, signals):
        return None
    monkeypatch.setattr(distill_service, "distill_facts", _fail)

    for _ in range(5):                       # five interactive failures
        await distill_service.distill_session("c1")

    assert len(await _events(wdb, "c1", "curation_failed")) == 0
    attempts = []
    monkeypatch.setattr(distill_service, "distill_facts",
                        lambda e, s: attempts.append(1) or _aw(None))
    await curation_loop.tick()
    assert attempts, "the sweep's own budget must be untouched by interactive failures"


async def test_give_up_marker_does_not_silence_a_manual_retry(wdb, monkeypatch):
    """A background give-up must never turn the user's manual 完结/distill into a
    silent no-op. The interactive path ignores the marker and, on success, replaces it
    with a normal one."""
    await _seed(wdb)
    await _enable(wdb)
    async with wdb() as db:
        db.add(DistilledSession(conversation_id="c1", spawn_id=1,
                                reason="curation_gave_up"))
        await db.commit()

    async def _facts(existing, signals):
        return ["用户偏好简短"]
    monkeypatch.setattr(distill_service, "distill_facts", _facts)

    n = await distill_service.distill_session("c1")

    assert n == 1, "the manual path must still work after a background give-up"
    async with wdb() as db:
        marks = (await db.execute(select(DistilledSession).where(
            DistilledSession.conversation_id == "c1"))).scalars().all()
        spawn = await db.get(Spawn, 1)
    assert [m.reason for m in marks] == [None], "success must replace the give-up marker"
    assert spawn.memory_facts == ["用户偏好简短"]


async def test_sweep_respects_the_per_tick_batch_limit(wdb, monkeypatch):
    swept = []
    monkeypatch.setattr(curation_loop, "_sweep_once",
                        lambda cid, **k: swept.append(cid) or _aw(None))
    for i in range(curation_loop.MAX_PER_TICK + 3):
        await _seed(wdb, conversation_id=f"conv{i}", spawn_id=i + 1)
    await _enable(wdb)

    await curation_loop.tick()
    assert len(swept) == curation_loop.MAX_PER_TICK


async def _aw(v):
    return v


async def test_cooldown_blocks_an_immediate_retry(wdb, monkeypatch):
    """A failed conversation is not retried until RETRY_COOLDOWN_S has passed — three
    strikes must mean three ATTEMPTS over time, not three ticks in one minute."""
    await _seed(wdb)
    await _enable(wdb)
    attempts = []

    async def _fail(existing, signals):
        attempts.append(1)
        return None
    monkeypatch.setattr(distill_service, "distill_facts", _fail)

    await curation_loop.tick()
    await curation_loop.tick()
    await curation_loop.tick()
    assert len(attempts) == 1, "the cooldown must suppress immediate retries"


# ---------------------------------------------------------------------------
# Lifespan wiring — no test in this repo asserts that the OTHER two background
# loops are actually started, so a loop can be fully unit-tested and still never
# run in production. Pin the wiring at the source level (the lifespan itself is
# not executed by the test suite).
# ---------------------------------------------------------------------------


def test_curation_loop_is_wired_into_the_app_lifespan():
    from pathlib import Path

    import server.main as main

    src = Path(main.__file__).read_text(encoding="utf-8")
    assert "curation_loop.start()" in src, (
        "the curation loop is never started — it would be dead code in production")
    assert "_curation.stop()" in src, (
        "the curation loop is never stopped — it would outlive shutdown")


# ---------------------------------------------------------------------------
# Review regressions (two-stage review, empirically reproduced)
# ---------------------------------------------------------------------------


async def test_idle_window_uses_the_whole_conversation_not_just_undistilled_rows(wdb):
    """The candidate filter (role=spawn_summary, unmarked) is a WHERE clause, so it
    applies BEFORE the GROUP BY: aggregating MAX(timestamp) over only those rows made a
    LIVE conversation look idle. Sweeping it early writes a NORMAL marker, which then
    permanently suppresses the real end-of-session distillation AND blocks the manual
    retry (that path only ignores a give-up marker)."""
    old = datetime.utcnow() - timedelta(hours=7)
    fresh = datetime.utcnow() - timedelta(minutes=1)
    async with wdb() as db:
        db.add(Spawn(id=1, name="S", domain_category="g", system_prompt="sp",
                     memory_facts=[]))
        db.add(ArslanMessage(conversation_id="live", role="user", content="早上的活",
                             timestamp=old))
        db.add(ArslanMessage(conversation_id="live", role="spawn_summary", content="产出",
                             display_content="产出", spawn_id=1, timestamp=old))
        # the user kept chatting with Arslan all day — the conversation is NOT idle
        db.add(ArslanMessage(conversation_id="live", role="user", content="还在聊",
                             timestamp=fresh))
        await db.commit()

    assert await curation_loop._candidates() == [], (
        "a conversation with recent activity must not be swept, even if its only "
        "undistilled spawn deliverable is old")


async def test_transient_strike_read_error_skips_but_does_not_give_up(wdb, monkeypatch):
    """Fail-closed for SPEND means skip this tick — not brand the conversation dead
    forever after zero real attempts."""
    await _seed(wdb)
    await _enable(wdb)

    async def _boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(curation_loop.recap_service, "count_events_strict", _boom)

    swept = []
    monkeypatch.setattr(curation_loop, "_sweep_once",
                        lambda cid, **k: swept.append(cid) or _aw(None))
    await curation_loop.tick()

    assert swept == [], "unknown strike count must not spend"
    async with wdb() as db:
        marks = (await db.execute(select(DistilledSession))).scalars().all()
    assert marks == [], "a transient read error must not write a TERMINAL give-up"


async def test_the_sweep_is_opt_in(wdb, monkeypatch):
    """Default OFF: the loop SPENDS, and until the proposal inbox has a UI its output
    is invisible — so it must not run for anyone who did not ask for it."""
    swept = []
    monkeypatch.setattr(curation_loop, "_sweep_once",
                        lambda cid, **k: swept.append(cid) or _aw(None))
    await _seed(wdb)                      # deliberately NOT enabled

    await curation_loop.tick()
    assert swept == [], "the curation sweep must be opt-in, not default-on"

    await _enable(wdb)
    await curation_loop.tick()
    assert swept == ["c1"], "and it must run once the user opts in"


async def test_a_proposed_marker_does_not_block_the_manual_path(wdb, monkeypatch):
    """propose_only writes a DISTINGUISHABLE marker: nothing reached memory, so the
    user asking for a real distillation must still get one (a plain marker made the
    manual path answer '0 spawns' forever while the material sat in an inbox with no
    UI)."""
    async def _facts(existing, signals):
        return ["用户偏好简短"]
    monkeypatch.setattr(distill_service, "distill_facts", _facts)
    await _seed(wdb)
    await _enable(wdb)

    await curation_loop.tick()
    async with wdb() as db:
        marks = (await db.execute(select(DistilledSession))).scalars().all()
        spawn = await db.get(Spawn, 1)
    assert [m.reason for m in marks] == ["curation_proposed"]
    assert spawn.memory_facts == [], "propose_only must not write memory"

    n = await distill_service.distill_session("c1")
    assert n == 1, "the manual path must still work after a proposal-only sweep"
    async with wdb() as db:
        marks = (await db.execute(select(DistilledSession))).scalars().all()
        spawn = await db.get(Spawn, 1)
    assert [m.reason for m in marks] == [None], "a real distill normalizes the marker"
    assert spawn.memory_facts == ["用户偏好简短"]
