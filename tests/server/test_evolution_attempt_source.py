"""批1 P1-P3: attempt provenance (`source`) and what the counters do with it.

`manual=True` has been a NO-OP parameter since the manual API was added: four occurrences
repo-wide (api/evolution.py:108, watcher.py:215 param, :218 docstring, :243) and not one of
them a read. enqueue_attempt's body never mentions it. `evolution_attempts` has no column
for it either, so a human's click and the background loop are indistinguishable everywhere.

That is not cosmetic. Two counters are derived by querying that table with NO provenance
filter, so a manual click corrupts the AUTO watcher's state:

  * `_consecutive_fails` — two manual clicks that fail the gate on quality push the AUTO
    backoff threshold from 10 to 40 (`_threshold` = 10 * min(2**fails, 8)).
  * `_last_attempt_started_at` — every attempt advances the "have enough new runs
    accumulated" cursor, including one refused by the budget before it consumed anything.

🔴 The correction that matters most here came from the plan review, not from me: my first
design filtered manual attempts OUT of `_consecutive_fails` entirely. That would ALSO have
removed a manual PASS's power to break the streak — and a manual pass is the user's only
way to rescue a spawn that has backed off to the 80 ceiling. It would have raised the very
threshold it exists to lower. So manual attempts are NEUTRAL WALLS: skipped for counting,
but a manual 'passed' still stops the scan.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from server.db.models import EvolutionAttempt, Setting
from server.services import evolution_loop, evolution_watcher

# `wdb` is a conftest fixture (shared with test_evolution_watcher.py); only the plain
# helpers are imported here.
from .test_evolution_watcher import _attempts, _drain, _fail_propose, _seed_runs, _spawn


async def _add(Session, spawn_id, *, outcome, source, minutes_ago=0):
    async with Session() as db:
        db.add(EvolutionAttempt(
            spawn_id=spawn_id, outcome=outcome, source=source, reason="",
            started_at=datetime.utcnow() - timedelta(minutes=minutes_ago)))
        await db.commit()


# ── P1/P2: the column exists and is actually written ──────────────────────────────


async def test_manual_and_auto_attempts_are_distinguishable(wdb, monkeypatch):
    """The whole point: after this, a row knows where it came from."""
    Session = wdb
    monkeypatch.setattr(evolution_loop, "propose_improvement", _fail_propose)
    sid = await _spawn(Session)

    await evolution_watcher.enqueue_attempt(sid, manual=True)
    await _drain()
    await _seed_runs(Session, sid, 20)
    await evolution_watcher.trigger_spawn(sid)
    await _drain()

    rows = await _attempts(Session, sid)
    assert [r.source for r in rows] == ["manual", "auto"]


async def test_legacy_rows_keep_null_meaning_unknown(wdb):
    """Rows written before the column existed are NOT backfilled to 'auto'. They predate
    any provenance record, and calling them auto would fabricate attribution for exactly
    the manual clicks this feature exists to account for."""
    Session = wdb
    sid = await _spawn(Session)
    await _add(Session, sid, outcome="failed", source=None)

    rows = await _attempts(Session, sid)
    assert rows[0].source is None


# ── P3: manual attempts are NEUTRAL WALLS in the fail streak ──────────────────────


async def test_manual_failures_do_not_inflate_the_auto_backoff(wdb):
    """Two impatient clicks must not quadruple the threshold the auto loop waits for."""
    Session = wdb
    sid = await _spawn(Session)
    await _add(Session, sid, outcome="failed", source="manual", minutes_ago=3)
    await _add(Session, sid, outcome="failed", source="manual", minutes_ago=2)

    async with Session() as db:
        assert await evolution_watcher._consecutive_fails(db, sid) == 0


async def test_a_manual_pass_still_rescues_a_backed_off_spawn(wdb):
    """🔴 The escape hatch. A spawn at the 80 ceiling can only be rescued by a PASS, and
    an auto pass is unreachable because reaching it requires the inflated threshold. So a
    manual 'passed' must still break the streak even though manual rows do not count."""
    Session = wdb
    sid = await _spawn(Session)
    for _ in range(3):
        await _add(Session, sid, outcome="failed", source="auto", minutes_ago=10)

    async with Session() as db:
        assert await evolution_watcher._consecutive_fails(db, sid) == 3
        assert evolution_watcher._threshold(3) == 80

    await _add(Session, sid, outcome="passed", source="manual")

    async with Session() as db:
        assert await evolution_watcher._consecutive_fails(db, sid) == 0, (
            "a manual pass must reset the backoff — it is the user's only escape hatch")
        assert evolution_watcher._threshold(0) == 10


async def test_the_table_driven_streak_case_the_review_demanded(wdb):
    """[auto failed, auto failed, manual passed, auto failed] — the case that separates
    'neutral wall' from 'filtered out'.

    Filtered out  -> the scan walks past the manual pass into the older failures = 3.
    Neutral wall  -> the manual pass stops the scan = 1.
    Today (no source column at all) it is also 1, because the pass breaks the loop. So the
    wall design PRESERVES current behavior here and only removes manual FAILURES from the
    count, which is exactly the intended scope.
    """
    Session = wdb
    sid = await _spawn(Session)
    await _add(Session, sid, outcome="failed", source="auto", minutes_ago=40)
    await _add(Session, sid, outcome="failed", source="auto", minutes_ago=30)
    await _add(Session, sid, outcome="passed", source="manual", minutes_ago=20)
    await _add(Session, sid, outcome="failed", source="auto", minutes_ago=10)

    async with Session() as db:
        assert await evolution_watcher._consecutive_fails(db, sid) == 1


async def test_null_source_rows_still_count_as_before(wdb):
    """Historical rows (source IS NULL) must behave exactly as they did pre-migration —
    a NULL-safe comparison, not `source != 'manual'` which is NULL for NULL and would
    silently drop every legacy row from the streak."""
    Session = wdb
    sid = await _spawn(Session)
    await _add(Session, sid, outcome="failed", source=None, minutes_ago=20)
    await _add(Session, sid, outcome="failed", source=None, minutes_ago=10)

    async with Session() as db:
        assert await evolution_watcher._consecutive_fails(db, sid) == 2


# ── P4(a): the cursor must not be advanced by an attempt that consumed nothing ─────


async def test_a_budget_refusal_does_not_orphan_banked_runs(wdb):
    """`skipped_budget` returns at watcher.py:189, BEFORE propose_improvement at :192 — it
    provably consumes nothing. Advancing the cursor past it strands every run banked so
    far: they fall behind the cursor and are never counted again, so raising the cap later
    does not bring them back."""
    Session = wdb
    sid = await _spawn(Session)
    await _seed_runs(Session, sid, 12, created_at=datetime.utcnow() - timedelta(hours=2))
    await _add(Session, sid, outcome="skipped_budget", source="auto", minutes_ago=30)

    async with Session() as db:
        since = await evolution_watcher._last_attempt_started_at(db, sid)
        assert since is None, "a budget refusal must not become the cursor"
        assert await evolution_watcher._new_replayable_run_count(db, sid, since) == 12


async def test_an_in_flight_attempt_still_holds_the_cursor(wdb):
    """🔴 NULL-safety, the other direction. An in-flight attempt has outcome IS NULL, and
    SQL `outcome != 'skipped_budget'` evaluates to NULL (not TRUE) for it — so a naive
    filter would DROP the running attempt from the cursor and let a second one be queued
    against the same corpus."""
    Session = wdb
    sid = await _spawn(Session)
    await _add(Session, sid, outcome=None, source="auto", minutes_ago=1)

    async with Session() as db:
        assert await evolution_watcher._last_attempt_started_at(db, sid) is not None, (
            "an in-flight attempt must still hold the cursor")


async def test_a_real_verdict_still_advances_the_cursor(wdb):
    """The anti-spin property C4 depends on: an attempt that actually ran must put those
    runs behind it, or the same corpus re-triggers every tick forever."""
    Session = wdb
    sid = await _spawn(Session)
    await _seed_runs(Session, sid, 12, created_at=datetime.utcnow() - timedelta(hours=2))
    await _add(Session, sid, outcome="failed", source="auto", minutes_ago=30)

    async with Session() as db:
        since = await evolution_watcher._last_attempt_started_at(db, sid)
        assert since is not None
        assert await evolution_watcher._new_replayable_run_count(db, sid, since) == 0


async def test_repeated_budget_refusals_are_rate_limited(wdb, monkeypatch):
    """Judgment call, flagged: with the cursor no longer advanced by `skipped_budget`, an
    over-budget spawn would otherwise write one attempt row every tick (300s) forever —
    zero LLM cost but unbounded row growth.

    The wall is a COOLDOWN rather than the eligibility gate, deliberately: an attempt row
    is still written, so `_verdict_code`'s skipped_budget branch still fires and the panel
    still tells the user why. (Moving the refusal into the gate instead would have made it
    invisible — that was a BLOCKER in my first plan.)
    """
    Session = wdb
    sid = await _spawn(Session)
    async with Session() as db:
        db.add(Setting(key="evolution_max_est_tokens", value="500"))
        await db.commit()
    await _seed_runs(Session, sid, 20)

    first = await evolution_watcher.trigger_spawn(sid)
    await _drain()
    assert first is not None
    rows = await _attempts(Session, sid)
    assert [r.outcome for r in rows] == ["skipped_budget"]

    second = await evolution_watcher.trigger_spawn(sid)
    await _drain()
    assert second is None, "a second refusal inside the cooldown must not write a row"
    assert len(await _attempts(Session, sid)) == 1
