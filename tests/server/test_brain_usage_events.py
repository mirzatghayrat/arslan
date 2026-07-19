"""D5: the per-event usage table (migration 0035) — write, retention, read.

Why a second table at all. `brain_usage` is a COUNTER (one row per entity, upsert):
it can say "this fact was used 12 times, most recently Tuesday" but not *when* the
other eleven were. The frontend's活跃时间条 needs the individual timestamps.

🔴 The user's hard condition for approving it: a retention ceiling. An append-only
event log with no cap is "只增不减 换张表复活" — the exact failure mode the counter
design avoided. So the table ships WITH its двойной gate (age + row count) and a
batched pruner, and the tests below include a backlog scenario, not just a happy path.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text as sa_text

from server.services import brain_usage

AUTH: dict[str, str] = {}


@pytest.fixture
async def usage_db(client, monkeypatch):
    from server.db import session as db_session

    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    return client


async def _count(maker) -> int:
    async with maker() as s:
        return (await s.execute(sa_text("SELECT COUNT(*) FROM brain_usage_events"))).scalar()


async def _seed_events(maker, rows):
    async with maker() as s:
        for kind, ref, ts in rows:
            await s.execute(sa_text(
                "INSERT INTO brain_usage_events (kind, ref_key, used_at, used_ref) "
                "VALUES (:k, :r, :t, NULL)"), {"k": kind, "r": ref, "t": ts})
        await s.commit()


# --------------------------------------------------------------------------- write


async def test_record_appends_an_event_per_call(usage_db):
    """The counter upserts; the event table must APPEND. Three calls = 1 counter row
    with count 3, and 3 event rows."""
    for _ in range(3):
        await brain_usage.record("learning", "learning:1", used_ref="conv:c1")

    async with usage_db.db_maker() as s:
        counter = (await s.execute(sa_text(
            "SELECT usage_count FROM brain_usage WHERE ref_key = 'learning:1'"))).scalar()
    assert counter == 3
    assert await _count(usage_db.db_maker) == 3


async def test_event_write_failure_never_breaks_the_counter(usage_db, monkeypatch):
    """record() is fail-open by contract (usage must never break retrieval). Adding a
    second write must not add a second way to fail — but it also must not silently
    lose the COUNTER write, which is the older, more important signal."""
    async with usage_db.db_maker() as s:
        await s.execute(sa_text("DROP TABLE brain_usage_events"))
        await s.commit()

    await brain_usage.record("note", "note:1", used_ref=None)

    async with usage_db.db_maker() as s:
        counter = (await s.execute(sa_text(
            "SELECT usage_count FROM brain_usage WHERE ref_key = 'note:1'"))).scalar()
    assert counter == 1, "the counter write must survive an event-table failure"


# ----------------------------------------------------------------------- retention


async def test_prune_drops_events_older_than_the_age_gate(usage_db):
    now = datetime.utcnow()
    await _seed_events(usage_db.db_maker, [
        ("note", "note:1", now - timedelta(days=40)),
        ("note", "note:1", now - timedelta(days=31)),
        ("note", "note:1", now - timedelta(days=29)),
        ("note", "note:1", now),
    ])
    deleted = await brain_usage.prune_events(retention_days=30, max_rows=1_000_000)
    assert deleted == 2
    assert await _count(usage_db.db_maker) == 2


async def test_prune_drops_the_oldest_rows_over_the_count_gate(usage_db):
    """The second gate. Age alone cannot bound a burst: a chatty week can blow past any
    row budget while every event is well inside the retention window."""
    now = datetime.utcnow()
    await _seed_events(usage_db.db_maker, [
        ("note", "note:1", now - timedelta(minutes=i)) for i in range(20)])

    await brain_usage.prune_events(retention_days=30, max_rows=5)
    assert await _count(usage_db.db_maker) == 5

    async with usage_db.db_maker() as s:
        oldest = (await s.execute(sa_text(
            "SELECT MIN(used_at) FROM brain_usage_events"))).scalar()
    assert oldest is not None
    # the survivors must be the NEWEST five, not an arbitrary five
    assert str(oldest) >= str(now - timedelta(minutes=5))


async def test_prune_is_batched_and_runs_to_completion_on_a_backlog(usage_db, monkeypatch):
    """🔴 The user's explicit nail: the DELETE must be batched (bounded rows per
    transaction) and must LOOP until clean — a single bounded DELETE would leave a
    backlog that never shrinks, which is the no-ceiling failure wearing a hat.

    Batch size is shrunk to 10 so the test can assert both properties directly:
    more than one batch ran, and nothing was left behind.
    """
    monkeypatch.setattr(brain_usage, "PRUNE_BATCH_ROWS", 10)
    now = datetime.utcnow()
    await _seed_events(usage_db.db_maker, [
        ("note", "note:1", now - timedelta(days=60)) for _ in range(95)])

    batches: list[int] = []
    real = brain_usage._delete_batch

    async def _spy(*a, **kw):
        n = await real(*a, **kw)
        batches.append(n)
        return n

    monkeypatch.setattr(brain_usage, "_delete_batch", _spy)
    deleted = await brain_usage.prune_events(retention_days=30, max_rows=1_000_000)

    assert deleted == 95
    assert await _count(usage_db.db_maker) == 0, "the loop must run until nothing is left"
    assert len(batches) > 1, "a 95-row backlog at batch=10 must take multiple batches"
    assert max(batches) <= 10, "no transaction may exceed the batch bound"


async def test_prune_with_retention_zero_is_a_no_op_not_a_purge(usage_db):
    """0 must mean 'disabled', matching run_debug_retention_days. Reading it as
    'delete everything older than now' would erase the whole log on a typo."""
    await _seed_events(usage_db.db_maker, [
        ("note", "note:1", datetime.utcnow() - timedelta(days=999))])
    assert await brain_usage.prune_events(retention_days=0, max_rows=0) == 0
    assert await _count(usage_db.db_maker) == 1


async def test_prune_is_fail_open(usage_db):
    async with usage_db.db_maker() as s:
        await s.execute(sa_text("DROP TABLE brain_usage_events"))
        await s.commit()
    assert await brain_usage.prune_events(retention_days=30, max_rows=10) == 0


# ---------------------------------------------------------------------- read endpoint


async def test_read_endpoint_returns_events_newest_first(usage_db):
    now = datetime.utcnow()
    await _seed_events(usage_db.db_maker, [
        ("note", "note:1", now - timedelta(hours=2)),
        ("learning", "learning:1", now - timedelta(hours=1)),
    ])
    body = (await usage_db.get("/api/v1/brain/usage-events", headers=AUTH)).json()
    assert [e["ref_key"] for e in body["events"]] == ["learning:1", "note:1"]
    assert body["truncated"] is False
    assert body["window_start"] is not None

    # 🔴 Timestamps must be PARSEABLE ISO-8601. These rows are read via raw SQL, so
    # SQLite hands back its storage form "YYYY-MM-DD HH:MM:SS.ffffff" — a space where
    # ISO wants a T. `new Date()` on that is implementation-defined (Chrome accepts it,
    # Safari returns Invalid Date), and unlike the older fields these are PLOTTED.
    for e in body["events"]:
        assert "T" in e["used_at"] and " " not in e["used_at"], e["used_at"]
        # ...and it must be marked UTC. The DB stores datetime.utcnow() (naive UTC);
        # a bare "2026-07-19T10:19:03" is parsed by `new Date()` as LOCAL time, which
        # shifts the entire plotted timeline by the viewer's offset.
        assert e["used_at"].endswith("Z"), e["used_at"]
        datetime.fromisoformat(e["used_at"].replace("Z", "+00:00"))
    assert body["window_start"].endswith("Z")


async def test_read_endpoint_is_honest_about_what_it_covers(usage_db):
    """🔴 record() has THREE call sites — material, learning, note (knowledge.py). There
    is no `record("profile", ...)` anywhere in the repo, so profile facts produce no
    events. A timeline that silently omits a whole kind while the graph shows four is a
    lie by omission, so the coverage is stated BY THE BACKEND rather than left to the
    frontend to remember."""
    body = (await usage_db.get("/api/v1/brain/usage-events", headers=AUTH)).json()
    assert set(body["covered_kinds"]) == {"material", "learning", "note"}
    assert "profile" not in body["covered_kinds"]
    note = body["coverage_note"]
    assert "profile" in note and ("retention" in note.lower() or "保留" in note)


async def test_read_endpoint_truncation_is_reported_not_hidden(usage_db):
    now = datetime.utcnow()
    await _seed_events(usage_db.db_maker, [
        ("note", "note:1", now - timedelta(minutes=i)) for i in range(10)])
    body = (await usage_db.get("/api/v1/brain/usage-events?limit=3",
                               headers=AUTH)).json()
    assert len(body["events"]) == 3
    assert body["truncated"] is True, (
        "a silently short list reads as 'quiet period' — the opposite of the truth")
    assert "truncat" in body["coverage_note"].lower()


async def test_limit_is_clamped_to_a_hard_ceiling(usage_db):
    """An unbounded limit is a self-inflicted DoS on an append-only table."""
    r = await usage_db.get("/api/v1/brain/usage-events?limit=999999", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["applied_limit"] == brain_usage.MAX_EVENT_PAGE


async def test_since_filters_the_window(usage_db):
    now = datetime.utcnow()
    await _seed_events(usage_db.db_maker, [
        ("note", "note:1", now - timedelta(days=10)),
        ("note", "note:2", now - timedelta(hours=1)),
    ])
    since = (now - timedelta(days=1)).isoformat()
    body = (await usage_db.get(f"/api/v1/brain/usage-events?since={since}",
                               headers=AUTH)).json()
    assert [e["ref_key"] for e in body["events"]] == ["note:2"]


async def test_unparsable_since_is_refused_not_ignored(usage_db):
    """Falling back to the default window would show a DIFFERENT range than asked for
    with no indication — the frontend would label it with the requested date."""
    r = await usage_db.get("/api/v1/brain/usage-events?since=yesterday", headers=AUTH)
    assert r.status_code == 422


# ------------------------------------------------------------------- loop placement


async def test_retention_runs_even_when_curation_is_switched_off(usage_db, monkeypatch):
    """🔴 Tripwire. `tick()` opens with the opt-in `_enabled()` gate (both switches
    default OFF); `brain_usage.record` appends UNCONDITIONALLY. If retention were moved
    inside tick(), it would never run on a default install and the table would grow
    forever — the "只增不减 换张表复活" failure the ceiling exists to prevent.

    So: run watch_loop with both switches off and assert the prune still happened.
    """
    import asyncio

    from server.services import curation_loop

    await _seed_events(usage_db.db_maker, [
        ("note", "note:1", datetime.utcnow() - timedelta(days=90))])

    async def _off() -> bool:
        return False

    monkeypatch.setattr(curation_loop, "_enabled", _off)

    stop = asyncio.Event()
    calls: list[int] = []
    real = curation_loop.prune_usage_events

    async def _spy():
        await real()
        calls.append(1)
        stop.set()

    monkeypatch.setattr(curation_loop, "prune_usage_events", _spy)
    await asyncio.wait_for(
        curation_loop.watch_loop(interval=0.01, initial_delay=0, stop_event=stop),
        timeout=5)

    assert calls, "retention must not sit behind the curation opt-in switch"
    assert await _count(usage_db.db_maker) == 0


async def test_a_tz_aware_since_is_converted_not_stripped(usage_db):
    """🔴 Dropping the offset instead of converting it shifts the window by the
    caller's UTC offset, silently returning a DIFFERENT range than asked for.

    Direction matters, and my first version of this test got it wrong — it asserted an
    EMPTY result, which stripping also produces, so it passed against the bug. With a
    +08:00 offset, stripping moves the bound eight hours FORWARD, i.e. narrows the
    window and wrongly EXCLUDES events. So: seed one event an hour ago, ask for "since
    2 hours ago" expressed in +08:00, and assert the event IS RETURNED. Under the
    stripping bug the bound lands six hours in the future and the list comes back empty.
    """
    from datetime import timezone
    from urllib.parse import quote

    now = datetime.utcnow()
    await _seed_events(usage_db.db_maker, [("note", "note:1", now - timedelta(hours=1))])

    since = (now.replace(tzinfo=timezone.utc) - timedelta(hours=2)).astimezone(
        timezone(timedelta(hours=8))).isoformat()
    assert "+08:00" in since

    # percent-encode: a bare "+" in a query string decodes to a SPACE, which the
    # endpoint then (correctly) refuses as unparsable.
    body = (await usage_db.get(f"/api/v1/brain/usage-events?since={quote(since)}",
                               headers=AUTH)).json()
    assert [e["ref_key"] for e in body["events"]] == ["note:1"], (
        "a 1h-old event is inside a 2h window; an empty list means the +08:00 offset "
        "was dropped rather than converted, pushing the bound into the future")


async def test_a_negative_offset_since_is_also_converted(usage_db):
    """The mirror direction: a -08:00 offset stripped would widen the window and
    wrongly INCLUDE older events. Both signs are checked so neither can regress."""
    from datetime import timezone
    from urllib.parse import quote

    now = datetime.utcnow()
    await _seed_events(usage_db.db_maker, [("note", "note:9", now - timedelta(hours=3))])

    since = (now.replace(tzinfo=timezone.utc) - timedelta(hours=2)).astimezone(
        timezone(timedelta(hours=-8))).isoformat()
    assert "-08:00" in since

    body = (await usage_db.get(f"/api/v1/brain/usage-events?since={quote(since)}",
                               headers=AUTH)).json()
    assert body["events"] == [], (
        "a 3h-old event is outside a 2h window; returning it means the -08:00 offset "
        "was dropped rather than converted, pulling the bound into the past")


async def test_coverage_note_does_not_equate_the_query_window_with_retention(usage_db):
    """window_start is the QUERY bound (default 7 days); retention is separate
    (default 30). Claiming everything before window_start was pruned is false for the
    entire fortnight between them."""
    note = (await usage_db.get("/api/v1/brain/usage-events", headers=AUTH)).json()[
        "coverage_note"]
    assert "not queried" in note
    assert "retention" in note.lower()


async def test_an_unencoded_offset_is_refused_rather_than_misread(usage_db):
    """A bare "+" in a query string decodes to a space, so "…+08:00" arrives as
    "… 08:00". Refusing it is right — silently reinterpreting it would be guessing at
    the caller's timezone, and that is the failure this endpoint is careful about."""
    r = await usage_db.get("/api/v1/brain/usage-events?since=2026-07-19T16:00:00+08:00",
                           headers=AUTH)
    assert r.status_code == 422, r.text
