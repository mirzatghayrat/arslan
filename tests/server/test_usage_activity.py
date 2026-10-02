"""0.1.50 Activity dashboard: run totals, percentiles and per-slice series on
GET /usage/summary (server/api/usage.py run_activity)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import server.db.session as db_session
from server.api.usage import DURATION_BANDS, _percentile, run_activity
from tests.server.test_usage_api import AUTH, SONNET, _ledger, _run, client  # noqa: F401

NOW = datetime(2026, 10, 2, 12, 0, 0)


def test_statuses_map_to_what_the_user_sees():
    rows = [("completed", 1000, NOW), ("recorded", 2000, NOW), ("scored", 3000, NOW),
            ("failed", 4000, NOW), ("cancelled", 5, NOW), ("interrupted", 5, NOW),
            ("recording", None, NOW)]
    totals, _ = run_activity(rows, [], NOW - timedelta(hours=24), NOW, "24h")
    assert (totals.total, totals.done, totals.failed, totals.stopped, totals.running) == (7, 3, 1, 2, 1)


def test_percentiles_use_finished_work_only():
    rows = [("completed", ms, NOW) for ms in (1000, 2000, 3000, 4000, 100_000)]
    rows += [("cancelled", 999_999, NOW), ("recording", None, NOW)]
    totals, _ = run_activity(rows, [], NOW - timedelta(hours=24), NOW, "24h")
    assert totals.p50_ms == 3000 and totals.p95_ms == 100_000


def test_nearest_rank_percentile():
    assert _percentile([], 0.95) is None
    assert _percentile([7], 0.95) == 7
    assert _percentile(list(range(1, 21)), 0.95) == 19 and _percentile(list(range(1, 21)), 0.5) == 10


def test_24h_has_hourly_slices_with_outcomes_durations_and_tokens():
    rows = [("completed", 5_000, NOW - timedelta(minutes=30)),          # last slice, <10s
            ("failed", 45_000, NOW - timedelta(minutes=10)),            # last slice, 30s–1m
            ("completed", 700_000, NOW - timedelta(hours=23, minutes=30))]  # first slice, >10m
    items = [("answer", None, None, 1, 1, False, 400, NOW - timedelta(minutes=5)),
             ("answer", None, None, 1, 1, False, 99, NOW - timedelta(hours=30))]   # outside
    _, bins = run_activity(rows, items, NOW - timedelta(hours=24), NOW, "24h")
    assert len(bins) == 24
    last, first = bins[-1], bins[0]
    assert (last.runs, last.failed, last.tokens_total) == (2, 1, 400)
    assert last.durations[0] == 1 and last.durations[2] == 1 and sum(last.durations) == 2
    assert first.runs == 1 and first.durations[len(DURATION_BANDS) - 1] == 1
    assert sum(b.runs for b in bins[1:-1]) == 0
    assert last.start_ts == int((NOW - timedelta(hours=1)).replace(tzinfo=timezone.utc).timestamp())


@pytest.mark.parametrize("rng,count,step", [("7d", 28, timedelta(hours=6)), ("30d", 30, timedelta(days=1))])
def test_slice_counts_per_range(rng, count, step):
    window = {"7d": timedelta(days=7), "30d": timedelta(days=30)}[rng]
    _, bins = run_activity([], [], NOW - window, NOW, rng)
    assert len(bins) == count and bins[1].start_ts - bins[0].start_ts == step.total_seconds()


async def test_summary_carries_the_dashboard(client):  # noqa: F811
    now = datetime.utcnow()
    async with db_session.AsyncSessionLocal() as db:
        ok = _run("c1", model=SONNET, provider="anthropic", tin=1000, tout=100, task_tokens=1100,
                  kind="host", created_at=now - timedelta(minutes=20))
        ok.status, ok.total_ms = "completed", 12_000
        bad = _run("c2", kind="host", created_at=now - timedelta(hours=3))
        bad.status, bad.total_ms = "failed", 2_000
        old = _run("c3", kind="host", created_at=now - timedelta(days=3))
        old.status, old.total_ms = "completed", 1
        replay = _run("c4", kind="replay", created_at=now - timedelta(minutes=5))
        db.add_all([ok, bad, old, replay])
        db.add(_ledger("c1", scope="router", model="mystery-1", total=50, estimated=True,
                       ts=now - timedelta(minutes=10)))
        await db.commit()
    body = (await client.get("/api/v1/usage/summary", params={"range": "24h"}, headers=AUTH)).json()
    assert body["runs"]["total"] == 2 and body["runs"]["done"] == 1 and body["runs"]["failed"] == 1
    assert body["runs"]["p95_ms"] == 12_000
    assert body["bin_seconds"] == 3600 and len(body["bins"]) == 24
    assert body["duration_bands"] == [label for _, label in DURATION_BANDS]
    assert sum(b["runs"] for b in body["bins"]) == 2 and sum(b["failed"] for b in body["bins"]) == 1
    assert body["tokens_total"] == sum(r["tokens_total"] for r in body["rows"]) == 1100 + 50 + 0
    assert body["usd_total"] == pytest.approx(1000 / 1e6 * 3 + 100 / 1e6 * 15)
    assert body["estimated_any"] is True


async def test_nothing_priceable_means_no_cost_not_zero(client):  # noqa: F811
    async with db_session.AsyncSessionLocal() as db:
        db.add(_ledger("c1", scope="router", model="mystery-1", total=50))
        await db.commit()
    body = (await client.get("/api/v1/usage/summary", params={"range": "24h"}, headers=AUTH)).json()
    assert body["tokens_total"] == 50 and body["usd_total"] is None
    assert body["runs"]["total"] == 0 and body["runs"]["p95_ms"] is None


def test_band_edges_are_upper_exclusive():
    """"<10s" means under ten seconds: exactly 10s is the next band."""
    from server.api.usage import _band
    assert _band(9_999) == 0 and _band(10_000) == 1 and _band(599_999) == 4 and _band(600_000) == 5
