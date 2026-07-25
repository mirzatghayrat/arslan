"""The new estimate fields, and the old ones they must NOT disturb.

🔴 Field existence is asserted through the HTTP endpoint, never at the service layer.
EstimateOut has no `extra` config, so pydantic silently drops anything undeclared at the
boundary: a new field can pass every service-level test and never reach a client, and a
deleted field can be resurrected by the schema's own default. That has now happened three
times in this repo (the D-round write-only int keys, last round's config_id write path,
and this model's `lower_bound`), which is why the rule is a rule.
"""
from __future__ import annotations

import datetime as dt

import pytest

from server.db.models import EvolutionAttempt, Run, Spawn
from server.services import evolution_estimate

AUTH: dict[str, str] = {}


@pytest.fixture
async def spawn_id(client, monkeypatch):
    from server.db import session as db_session

    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    async with client.db_maker() as s:
        sp = Spawn(name="S", domain_category="g", system_prompt="p")
        s.add(sp)
        await s.commit()
        return sp.id


async def _get(client, sid):
    r = await client.get(f"/api/v1/spawns/{sid}/evolve/estimate", headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


# ── the frozen block ────────────────────────────────────────────────────────────────


async def test_the_old_fields_still_reach_the_client(client, spawn_id):
    """They are wrong, and they stay. evolution_watcher compares `est_tokens` against
    evolution_max_est_tokens; dropping the key makes `int(None or 0)` = 0, which never
    exceeds any cap — the spend gate would go quietly inert while still showing a value in
    Settings. A switch that looks armed and is not is worse than a wrong number."""
    body = await _get(client, spawn_id)
    for key in ("pairs", "dispatches", "judge_calls", "optimizer_calls", "synth_calls",
                "est_tokens"):
        assert key in body, f"{key} disappeared — the budget gate reads it"
    assert isinstance(body["est_tokens"], int), "est_tokens must never be null"
    assert body["lower_bound"] is True, (
        "the 409 spend-confirmation dialog reads est_is_lower_bound from this; flipping it "
        "to False would assert the opposite of the truth")


async def test_est_tokens_keeps_the_old_live_pricing(client, spawn_id, monkeypatch):
    """🔴 Pins the NUMBER, not the shape. Repricing est_tokens with the replay population
    (which is the correct population, and is what the new field uses) would drop it to
    roughly 1/2.5 — no line of the gate changes, but the value it compares moves, so the
    spend gate widens 2.5x silently. This test is the thing standing between a correct
    refactor and a quietly loosened gate.

    Seeded so the two populations give visibly different answers: live=1000, replay=100.
    """
    from server.db import session as db_session

    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    async with client.db_maker() as s:
        for _ in range(3):
            s.add(Run(conversation_id="c", spawn_id=spawn_id, kind="live", epoch=1, task_tokens=1000,
                      created_at=dt.datetime.utcnow()))
            s.add(Run(conversation_id="c", spawn_id=spawn_id, kind="replay", epoch=1, task_tokens=100,
                      created_at=dt.datetime.utcnow()))
        await s.commit()

    async with client.db_maker() as s:
        est = await evolution_estimate.estimate(s, spawn_id)

    expected = int(1000.0 * est["dispatches"]
                   + evolution_estimate.AVG_JUDGE_TOKENS * est["judge_calls"])
    assert est["est_tokens"] == expected, (
        "est_tokens moved. If this is a deliberate repricing, the spend gate's threshold "
        "must be revisited in the same change — see evolution_watcher.py:259")


# ── the derived ceiling ─────────────────────────────────────────────────────────────


async def test_new_fields_reach_the_client(client, spawn_id):
    body = await _get(client, spawn_id)
    for key in ("propose_pairs", "val_pairs", "dispatches_max", "judge_calls_max",
                "optimizer_calls_max", "basis", "avg_replay_tokens", "avg_replay_n",
                "tokens_projected", "tokens_projected_unavailable_reason"):
        assert key in body, (
            f"{key} never crossed the HTTP boundary — EstimateOut drops undeclared fields "
            "silently, so a service-level assertion would have passed")
    assert body["basis"] == "max"


async def test_no_min_fields_are_emitted(client, spawn_id):
    """The true minimum is ZERO: propose_improvement returns before any dispatch when the
    spawn is gone or the val slice is empty, and a real attempt (id 7) took that path.
    Emitting a constant 0 would invite someone to build on it."""
    body = await _get(client, spawn_id)
    assert not [k for k in body if k.endswith("_min")], (
        "a *_min field is a constant 0 dressed up as information")


async def test_val_cap_comes_from_the_loop_signature(client, spawn_id, monkeypatch):
    """The ceiling turns on val_cap. Hardcoding it would make the number right once and
    wrong the moment anyone tunes the loop — which is the exact failure the old formula
    had (it restated the loop instead of reading it)."""
    import inspect

    from server.services import evolution_loop, replay_gate

    # 🔴 A corpus big enough that val_cap BINDS. With an empty corpus val_pairs is 0 no
    # matter what val_cap says, so the assertion below holds for a hardcoded cap too —
    # the test would pass against the very thing it exists to forbid.
    corpus = ([{"run_id": 100 + i, "task": f"t{i}", "split_side": "propose",
                "corpus_label": "real", "score": 3.0} for i in range(18)]
              + [{"run_id": 200 + i, "task": f"h{i}", "split_side": "holdout",
                  "corpus_label": "real", "score": 3.0} for i in range(10)])

    async def fake_corpus(db, sid, *, baseline_started_at=None, mint=False):
        return list(corpus)
    monkeypatch.setattr(replay_gate, "build_corpus", fake_corpus)

    before = (await _get(client, spawn_id))["val_pairs"]
    assert before == 6, f"fixture is not exercising the cap (val_pairs={before})"

    orig = evolution_loop.propose_improvement
    sig = inspect.signature(orig)
    bumped = sig.replace(parameters=[
        p.replace(default=1) if p.name == "val_cap" else p
        for p in sig.parameters.values()])
    monkeypatch.setattr(orig, "__signature__", bumped, raising=False)

    after = (await _get(client, spawn_id))["val_pairs"]
    assert after <= 1, f"val_pairs ignored the signature's val_cap (before={before})"


# ── pricing, by identity ────────────────────────────────────────────────────────────


async def test_no_ledger_yields_null_not_zero(client, spawn_id):
    """🔴 null, never 0. Zero reads as "cheap" — to a UI, and to anyone who later wires a
    cap to it. That is the direction attempt 7 already failed in: avg_run=0 collapsed its
    estimate to judge-only, so the spawn with the LEAST evidence reported the SMALLEST
    number. Unknown must look unknown.

    Today this is every install: `actual` has never been written.
    """
    body = await _get(client, spawn_id)
    assert body["avg_replay_tokens"] is None
    assert body["tokens_projected"] is None
    assert body["avg_replay_n"] == 0
    assert body["tokens_projected_unavailable_reason"]


async def test_pricing_comes_from_the_actual_ledger_by_identity(client, spawn_id):
    """Mean per SUCCESSFUL replay dispatch, aggregated over attempts.

    Two rows with different shapes so the arithmetic is pinned rather than shape-checked,
    and one with failed dispatches so the denominator's correction is visible:
        (600 + 400) / ((10-0) + (10-5)) = 1000 / 15
    A denominator that forgot to subtract failures would give 1000/20 = 50.0 — a 33% cheaper
    per-dispatch price, in the direction that under-states cost.
    """
    async with client.db_maker() as s:
        s.add(EvolutionAttempt(spawn_id=spawn_id, outcome="failed",
                               actual={"dispatches": 10, "failed_dispatches": 0,
                                       "dispatch_tokens": 600}))
        s.add(EvolutionAttempt(spawn_id=spawn_id, outcome="passed",
                               actual={"dispatches": 10, "failed_dispatches": 5,
                                       "dispatch_tokens": 400}))
        await s.commit()

    body = await _get(client, spawn_id)
    assert body["avg_replay_n"] == 15
    assert body["avg_replay_tokens"] == pytest.approx(1000 / 15)
    assert body["tokens_projected"] == int(
        (1000 / 15) * body["dispatches_max"]
        + evolution_estimate.AVG_JUDGE_TOKENS * body["judge_calls_max"])


async def test_attempts_without_actual_are_ignored(client, spawn_id):
    """All ten rows in the wild are like this. A None `actual` must not count as a
    zero-token attempt, which would drag the mean toward zero — again in the
    under-stating direction."""
    async with client.db_maker() as s:
        s.add(EvolutionAttempt(spawn_id=spawn_id, outcome="failed", actual=None))
        s.add(EvolutionAttempt(spawn_id=spawn_id, outcome="passed",
                               actual={"dispatches": 4, "failed_dispatches": 0,
                                       "dispatch_tokens": 800}))
        await s.commit()

    body = await _get(client, spawn_id)
    assert body["avg_replay_n"] == 4, "the actual-less attempt was counted"
    assert body["avg_replay_tokens"] == pytest.approx(200.0)


@pytest.mark.parametrize("propose,expected_val", [(9, 3), (10, 3), (11, 3), (12, 4), (2, 0)])
async def test_val_pairs_is_floor_not_ceil(client, spawn_id, monkeypatch, propose,
                                           expected_val):
    """🔴 Pins the VALUE, because a ratio cannot see this.

    `_subsplit_propose` sends index i to val iff `i % 3 == 2`, which is floor(n/3). ceil
    differs for two out of every three sizes — and the difference is small enough that the
    dry-run's tightness ratio still passes (with propose=10 a ceil-based ceiling is 76 vs a
    real 64: 84%, above the 80% floor). So the ratio test cannot discriminate here and this
    one must, by asserting the number itself at sizes where floor and ceil disagree.

    9 and 12 are multiples of three (floor == ceil — included as controls that the fixture
    machinery works); 10 and 11 are the discriminating cases; 2 pins the sub-split floor.
    """
    from server.services import replay_gate

    corpus = ([{"run_id": 100 + i, "task": f"t{i}", "split_side": "propose",
                "corpus_label": "real", "score": 3.0} for i in range(propose)]
              + [{"run_id": 200 + i, "task": f"h{i}", "split_side": "holdout",
                  "corpus_label": "real", "score": 3.0} for i in range(10)])

    async def fake_corpus(db, sid, *, baseline_started_at=None, mint=False):
        return list(corpus)
    monkeypatch.setattr(replay_gate, "build_corpus", fake_corpus)

    body = await _get(client, spawn_id)
    assert body["propose_pairs"] == propose
    assert body["val_pairs"] == expected_val, (
        f"propose={propose}: floor gives {propose // 3}, ceil gives {-(-propose // 3)}")
