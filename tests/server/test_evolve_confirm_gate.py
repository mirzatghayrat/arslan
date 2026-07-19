"""批1 P5: the server-side spend gate on POST /spawns/{id}/evolve.

The dogfooding report was "I did not know what to do next, so I clicked ENQUEUE several
times". Reading the code produced a better explanation than the one in the report: the
estimate IS already shown before the button renders (the button is nested inside
`{estimate && ...}`), but NOTHING updates after the click — no polling, no WS event — so
the attempt finishes minutes later and the UI never says so. A button that does nothing
visible gets clicked again.

Two fixes follow from that, and this file is the executing-side half: a click that will
re-run the SAME corpus that already failed is refused with a structured 409 the frontend
renders as a confirmation. Spend is the executing side, so the gate is FAIL-CLOSED — a
body-less legacy call has no `force`, so the gate applies.

🔴 What the gate must NOT do (plan review): it must not fire after `skipped_structural`.
The eligibility panel's own copy tells the user to click evolve in exactly that state, to
trigger the synthetic holdout top-up. A gate contradicting the app's own instructions is
worse than no gate.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from server.db.models import EvolutionAttempt, Run, Spawn
from server.services import evolution_watcher

AUTH: dict[str, str] = {}


@pytest.fixture
async def evo(client, monkeypatch):
    """The evolve route opens its own sessions through the watcher, so point the
    production sessionmaker at the test DB (the house rule for any endpoint that does not
    take Depends(get_session))."""
    from server.db import session as db_session
    from server.services import evolution_estimate

    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)

    async def fake_estimate(db, spawn_id):
        return {"pairs": 4, "dispatches": 56, "judge_calls": 56, "optimizer_calls": 3,
                "synth_calls": 0, "est_tokens": 18400, "lower_bound": True}

    monkeypatch.setattr(evolution_estimate, "estimate", fake_estimate)

    # 🔴 The original fixture DEFINED a `never_run` guard and never installed it — an
    # assertion that could not fire, while every 202 test launched a REAL supervised
    # background evolution task (the suite took two minutes).
    #
    # A raising guard is the wrong stub, though: the 202 tests are SUPPOSED to enqueue —
    # that is what they assert. So stub propose_improvement with a fast structural no-op.
    # Nothing real runs, the supervised task finishes immediately, and the gate tests
    # still prove their point by asserting on the response and the attempt rows.
    async def _noop_propose(spawn_id, **k):
        return {"proposal_id": None, "candidate_prompt": None,
                "gate": {"passed": False, "reason": "length_cap", "aggregate": None},
                "evidence": {}}

    from server.services import evolution_loop

    monkeypatch.setattr(evolution_loop, "propose_improvement", _noop_propose)

    async with client.db_maker() as s:
        s.add(Spawn(id=1, name="S", domain_category="x", system_prompt="P",
                    generation_level=1, config={}))
        await s.commit()
    evolution_watcher._running_spawns.clear()
    yield client, _noop_propose

    # 🔴 DRAIN, do not cancel. The 202 tests legitimately enqueue a supervised background
    # task; if it outlives the test, the `client` fixture disposes its engine underneath
    # it and the task's next DB touch raises "no active connection" — which then HANGS
    # the connection pool's teardown until pytest-timeout kills the run at 120s. That is
    # what installing the (previously inert) propose stub exposed: these tests were
    # always launching real background work, it just used to die fast enough not to
    # collide. This fixture depends on `client`, so its teardown runs FIRST — draining
    # here is correctly ordered against the engine disposal.
    for _ in range(50):
        pending = [x for x in evolution_watcher._tasks if not x.done()]
        if not pending:
            break
        await asyncio.gather(*pending, return_exceptions=True)
    evolution_watcher._tasks.clear()
    evolution_watcher._running_spawns.clear()


async def _attempt(client, *, outcome, reason, minutes_ago=10, source="auto"):
    async with client.db_maker() as s:
        s.add(EvolutionAttempt(
            spawn_id=1, outcome=outcome, reason=reason, source=source, estimate={},
            started_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
            finished_at=datetime.utcnow() - timedelta(minutes=minutes_ago - 1)))
        await s.commit()


async def _runs(client, n, *, minutes_ago=5):
    async with client.db_maker() as s:
        for i in range(n):
            s.add(Run(conversation_id="c", spawn_id=1, user_message=f"t{i}",
                      task_tokens=100, status="scored", kind="live", epoch=1,
                      created_at=datetime.utcnow() - timedelta(minutes=minutes_ago)))
        await s.commit()


# ── the gate fires ────────────────────────────────────────────────────────────────


async def test_same_corpus_as_a_failed_attempt_is_refused_with_a_usable_body(evo):
    """The refusal has to carry everything the dialog needs, because the frontend must
    not invent the explanation — same rule as D5's coverage_note."""
    client, _ = evo
    await _attempt(client, outcome="failed", reason="holdout_winrate")

    r = await client.post("/api/v1/spawns/1/evolve", json={}, headers=AUTH)
    assert r.status_code == 409, r.text
    body = r.json()["detail"]
    assert body["code"] == "same_corpus_as_failed_attempt"
    assert body["last_outcome"] == "failed"
    assert body["last_reason"] == "holdout_winrate"
    assert body["new_runs_since"] == 0
    assert body["est_tokens"] == 18400
    assert body["last_attempt_id"] is not None


async def test_a_body_less_legacy_call_is_still_gated(evo):
    """FAIL-CLOSED: no body means no `force`, so the gate applies. A caller that predates
    the gate must not be silently exempt from it — that is the whole executing-side rule."""
    client, _ = evo
    await _attempt(client, outcome="failed", reason="holdout_winrate")

    r = await client.post("/api/v1/spawns/1/evolve", headers=AUTH)
    assert r.status_code == 409, r.text


async def test_force_true_goes_through(evo):
    client, _ = evo
    await _attempt(client, outcome="failed", reason="holdout_winrate")

    r = await client.post("/api/v1/spawns/1/evolve",
                          json={"force": True}, headers=AUTH)
    assert r.status_code == 202, r.text
    assert r.json()["attempt_id"] is not None


async def test_the_forced_attempt_is_recorded_as_manual(evo):
    client, _ = evo
    await _attempt(client, outcome="failed", reason="holdout_winrate")
    await client.post("/api/v1/spawns/1/evolve", json={"force": True}, headers=AUTH)

    async with client.db_maker() as s:
        from sqlalchemy import select
        rows = (await s.execute(select(EvolutionAttempt).order_by(
            EvolutionAttempt.id))).scalars().all()
    assert rows[-1].source == "manual"


# ── the gate stays out of the way ─────────────────────────────────────────────────


async def test_new_material_since_the_failure_is_not_gated(evo):
    """The gate is about re-running the SAME data, not about failure history."""
    client, _ = evo
    await _attempt(client, outcome="failed", reason="holdout_winrate", minutes_ago=60)
    await _runs(client, 3, minutes_ago=5)

    r = await client.post("/api/v1/spawns/1/evolve", json={}, headers=AUTH)
    assert r.status_code == 202, r.text


async def test_a_first_ever_attempt_is_not_gated(evo):
    client, _ = evo
    r = await client.post("/api/v1/spawns/1/evolve", json={}, headers=AUTH)
    assert r.status_code == 202, r.text


async def test_a_structural_skip_is_NOT_gated(evo):
    """🔴 The eligibility panel tells the user to click evolve in exactly this state, so
    that the gate can mint the synthetic holdout top-up. Refusing here would make the app
    contradict its own instructions."""
    client, _ = evo
    await _attempt(client, outcome="skipped_structural", reason="insufficient_holdout")

    r = await client.post("/api/v1/spawns/1/evolve", json={}, headers=AUTH)
    assert r.status_code == 202, r.text


async def test_an_infra_error_is_not_gated(evo):
    """'error' says nothing about the corpus — retrying after a dead adapter is repaired
    is exactly the right move, and the user should not have to force it."""
    client, _ = evo
    await _attempt(client, outcome="error", reason="RuntimeError: adapter down")

    r = await client.post("/api/v1/spawns/1/evolve", json={}, headers=AUTH)
    assert r.status_code == 202, r.text


async def test_a_passed_attempt_is_not_gated(evo):
    client, _ = evo
    await _attempt(client, outcome="passed", reason="gate passed")

    r = await client.post("/api/v1/spawns/1/evolve", json={}, headers=AUTH)
    assert r.status_code == 202, r.text


async def test_an_in_flight_attempt_still_returns_null_not_a_gate_error(evo):
    """Concurrency=1 predates this gate and has its own contract (202 + attempt_id null).
    The gate must not turn that into a 409 the frontend would render as a spend warning."""
    client, _ = evo
    evolution_watcher._running_spawns.add(1)

    r = await client.post("/api/v1/spawns/1/evolve", json={}, headers=AUTH)
    assert r.status_code == 202, r.text
    assert r.json()["attempt_id"] is None


async def test_a_stranded_in_flight_attempt_does_not_disable_the_gate(evo):
    """`outcome.is_not(None)` is the only thing stopping an abandoned in-flight row (a
    crash mid-attempt leaves outcome NULL forever) from becoming "the last attempt" and
    silently switching the gate off. Every test in this file passed with that clause
    deleted, so it is pinned here explicitly."""
    client, _ = evo
    await _attempt(client, outcome="failed", reason="holdout_winrate", minutes_ago=60)
    await _attempt(client, outcome=None, reason="", minutes_ago=30)   # stranded

    r = await client.post("/api/v1/spawns/1/evolve", json={}, headers=AUTH)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["last_outcome"] == "failed"
