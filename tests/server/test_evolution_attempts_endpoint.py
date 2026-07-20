"""A: every attempt's real cost must be reachable — including the ones that produced nothing.

`actual` has been recorded since the previous round, but the ONLY endpoint that surfaces
it joins on `EvolutionAttempt.proposal_id == proposal_id` (api/evolution.py). An attempt
that ended `failed`, `error` or `skipped_structural` has proposal_id NULL, so its cost is
in the database and visible nowhere — and those are exactly the attempts whose cost most
needs to be seen, because the user paid and got nothing back.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from server.db.models import EvolutionAttempt, Spawn

AUTH: dict[str, str] = {}


@pytest.fixture
async def seeded(client):
    async with client.db_maker() as s:
        s.add(Spawn(id=1, name="S", domain_category="x", system_prompt="P",
                    generation_level=1, config={}))
        now = datetime.utcnow()
        s.add(EvolutionAttempt(
            spawn_id=1, outcome="failed", reason="holdout_winrate", source="auto",
            started_at=now - timedelta(hours=3), finished_at=now - timedelta(hours=2),
            estimate={"est_tokens": 40000},
            actual={"est_tokens": 12000, "dispatch_tokens": 10000, "direct_tokens": 2000,
                    "dispatches": 6, "judge_calls": 4, "optimizer_calls": 3,
                    "synth_calls": 0, "pairs": 3, "failed_dispatches": 0,
                    "estimated": False}))
        s.add(EvolutionAttempt(
            spawn_id=1, outcome="passed", reason="gate passed", source="manual",
            proposal_id=99, started_at=now - timedelta(hours=1), finished_at=now,
            estimate={"est_tokens": 40000},
            actual={"est_tokens": 9000, "dispatch_tokens": 8000, "direct_tokens": 1000,
                    "dispatches": 5, "judge_calls": 2, "optimizer_calls": 1,
                    "synth_calls": 0, "pairs": 3, "failed_dispatches": 1,
                    "estimated": True}))
        s.add(EvolutionAttempt(spawn_id=1, outcome=None, source="auto",
                               started_at=now, estimate={}))
        await s.commit()
    return client


async def test_a_FAILED_attempt_cost_is_reachable(seeded):
    """🔴 The whole point. Before this endpoint its `actual` existed only in the DB."""
    r = await seeded.get("/api/v1/spawns/1/evolution/attempts", headers=AUTH)
    assert r.status_code == 200, r.text
    rows = r.json()["attempts"]
    failed = next(a for a in rows if a["outcome"] == "failed")
    assert failed["actual"]["est_tokens"] == 12000
    assert failed["proposal_id"] is None, (
        "this is precisely the shape the proposal-join endpoint cannot reach")


async def test_it_lists_attempts_newest_first_with_the_fields_a_cost_view_needs(seeded):
    r = await seeded.get("/api/v1/spawns/1/evolution/attempts", headers=AUTH)
    rows = r.json()["attempts"]
    assert [a["outcome"] for a in rows] == [None, "passed", "failed"]
    keys = set(rows[1])
    assert {"id", "outcome", "reason", "source", "started_at", "finished_at",
            "estimate", "actual", "proposal_id"} <= keys


async def test_an_in_flight_attempt_reports_no_cost_rather_than_zero(seeded):
    """A running attempt has actual=NULL. Rendering that as 0 would claim it has cost
    nothing so far, which is the opposite of true."""
    rows = (await seeded.get("/api/v1/spawns/1/evolution/attempts", headers=AUTH)).json()["attempts"]
    running = next(a for a in rows if a["outcome"] is None)
    assert running["actual"] is None


async def test_the_totals_are_computed_only_over_attempts_that_reported(seeded):
    """🔴 Summing a NULL as zero would understate the total AND make an in-flight attempt
    look free. The payload says how many attempts the total covers so the number is
    never read as 'everything this spawn ever spent'."""
    body = (await seeded.get("/api/v1/spawns/1/evolution/attempts", headers=AUTH)).json()
    assert body["totals"]["est_tokens"] == 21000        # 12000 + 9000, not the NULL one
    assert body["totals"]["counted_attempts"] == 2
    assert body["totals"]["total_attempts"] == 3


async def test_the_totals_admit_when_any_component_was_a_heuristic(seeded):
    """One attempt carries estimated=True, so the SUM is partly a guess and must say so
    rather than presenting a clean number."""
    body = (await seeded.get("/api/v1/spawns/1/evolution/attempts", headers=AUTH)).json()
    assert body["totals"]["estimated"] is True
    assert body["totals"]["failed_dispatches"] == 1


async def test_limit_is_clamped(seeded):
    r = await seeded.get("/api/v1/spawns/1/evolution/attempts?limit=99999", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["applied_limit"] <= 200


async def test_a_truncated_page_says_so_instead_of_looking_complete(seeded):
    """🔴 totals are summed over the PAGE. Reporting the page size as total_attempts made
    a truncated, understated total indistinguishable from a complete one — on a spawn
    with hundreds of older attempts, `counted == total` would read as "this is everything
    it ever spent"."""
    body = (await seeded.get("/api/v1/spawns/1/evolution/attempts?limit=1",
                             headers=AUTH)).json()
    assert len(body["attempts"]) == 1
    assert body["totals"]["total_attempts"] == 3, "must count the spawn, not the page"
    assert body["totals"]["truncated"] is True
    assert body["totals"]["covers_all_attempts"] is False


async def test_a_complete_view_says_that_too(seeded):
    body = (await seeded.get("/api/v1/spawns/1/evolution/attempts", headers=AUTH)).json()
    assert body["totals"]["truncated"] is False
    # one attempt is still in flight, so the SUM does not cover every attempt
    assert body["totals"]["covers_all_attempts"] is False
    assert body["totals"]["counted_attempts"] == 2
    assert body["totals"]["total_attempts"] == 3


async def test_an_unknown_spawn_404s_rather_than_reporting_zero_spend(seeded):
    """"this spawn cost nothing" and "there is no such spawn" are different facts."""
    r = await seeded.get("/api/v1/spawns/9999/evolution/attempts", headers=AUTH)
    assert r.status_code == 404, r.text
