"""The spend gate, moved off the token estimate and onto the derived dispatch ceiling.

Why it moved: the old `est_tokens` over-estimates 3.7-5.2x (measured), so a cap set from
what evolution ACTUALLY costs would be breached on every attempt — `skipped_budget`
forever. The gate failed in the direction where setting a limit switches the feature off,
and the user would have no way to see why. `dispatches_max` is a pure count, proven tight
by the dry-run harness (94-97% utilisation), and carries none of the pricing problem.

🔴 The central case here is a discrimination, not a value. Reading the projection as
`int(est.get("dispatches_max") or 0)` merges two states that must not merge:

  (A) an estimate written by the OLD schema — passing is correct, it matches today's
      behaviour, and it is not hypothetical: evolution_watcher reads the estimate stored
      at ENQUEUE time, so a queued attempt genuinely spans a deployment;
  (B) a NEW-schema estimate missing the key — structural damage. Passing it silently is a
      spend gate that fails OPEN, i.e. last round's BLOCKER 1 wearing a different field.

`basis: "max"` is the discriminator: only the new estimator emits it.
"""
from __future__ import annotations

from server.db.models import EvolutionAttempt, Setting, Spawn
from server.services import evolution_loop, evolution_watcher, settings_service

AUTH: dict[str, str] = {}


async def _spawn(Session) -> int:
    async with Session() as db:
        sp = Spawn(name="S", domain_category="g", system_prompt="p")
        db.add(sp)
        await db.commit()
        return sp.id


async def _attempt(Session, sid: int, estimate: dict) -> int:
    async with Session() as db:
        a = EvolutionAttempt(spawn_id=sid, estimate=estimate)
        db.add(a)
        await db.commit()
        return a.id


async def _outcome(Session, attempt_id: int):
    async with Session() as db:
        return (await db.get(EvolutionAttempt, attempt_id)).outcome


async def _set_cap(Session, value: str) -> None:
    async with Session() as db:
        db.add(Setting(key="evolution_max_dispatches", value=value))
        await db.commit()


# ── the setting itself ──────────────────────────────────────────────────────────────


async def test_new_cap_round_trips_through_the_api(client):
    """Through HTTP, both directions. The int-key registry test covers the read path
    structurally; this covers that a value a user actually PUTs comes back."""
    for value in (250, 999):
        r = await client.put("/api/v1/settings",
                             json={"evolution_max_dispatches": value}, headers=AUTH)
        assert r.status_code == 200, r.text
        assert r.json()["evolution_max_dispatches"] == value
        got = await client.get("/api/v1/settings", headers=AUTH)
        assert got.json()["evolution_max_dispatches"] == value


async def test_the_old_token_cap_key_is_gone(client):
    """Deleted, not renamed. Renaming while changing the unit is a silent-corruption trap:
    a stored 30,000,000 would become a '30 million dispatch' cap, which is no cap at all,
    and no conversion is honest because the token-per-dispatch figure is exactly what we
    do not reliably know."""
    body = (await client.get("/api/v1/settings", headers=AUTH)).json()
    assert "evolution_max_est_tokens" not in body
    assert not hasattr(settings_service, "evolution_max_est_tokens")


async def test_no_default_cap(client):
    """Unset = no gate, still. The `actual` ledger is empty on every install, so there is
    no distribution to pick a number from. This round delivers a cap that CAN be set
    correctly, not a cap that IS set."""
    body = (await client.get("/api/v1/settings", headers=AUTH)).json()
    assert body["evolution_max_dispatches"] is None


# ── the gate ────────────────────────────────────────────────────────────────────────


async def test_over_the_dispatch_cap_is_refused(wdb, monkeypatch):
    Session = wdb
    called = {"ran": False}

    async def spy(spawn_id, **k):
        called["ran"] = True
        return {"proposal_id": None, "candidate_prompt": None,
                "gate": {"passed": False, "reason": "x", "aggregate": None}, "evidence": {}}
    monkeypatch.setattr(evolution_loop, "propose_improvement", spy)

    sid = await _spawn(Session)
    await _set_cap(Session, "50")
    aid = await _attempt(Session, sid, {"basis": "max", "dispatches_max": 104})
    await evolution_watcher._perform_attempt(aid, sid)

    assert await _outcome(Session, aid) == "skipped_budget"
    assert called["ran"] is False, "the loop ran anyway — the gate did not gate"


async def test_under_the_dispatch_cap_runs(wdb, monkeypatch):
    """The other direction. Without it, 'refused' is satisfied by a gate that refuses
    everything — including a cap set generously enough to allow the work."""
    Session = wdb
    called = {"ran": False}

    async def spy(spawn_id, **k):
        called["ran"] = True
        return {"proposal_id": None, "candidate_prompt": None,
                "gate": {"passed": False, "reason": "x", "aggregate": None}, "evidence": {}}
    monkeypatch.setattr(evolution_loop, "propose_improvement", spy)

    sid = await _spawn(Session)
    await _set_cap(Session, "500")
    aid = await _attempt(Session, sid, {"basis": "max", "dispatches_max": 104})
    await evolution_watcher._perform_attempt(aid, sid)

    assert called["ran"] is True, "under the cap and still refused"
    assert await _outcome(Session, aid) != "skipped_budget"


# ── the discrimination the round exists for ─────────────────────────────────────────


async def test_an_OLD_schema_estimate_is_allowed_through(wdb, monkeypatch):
    """(A) A row enqueued before this deployment. It has no `basis`, so it cannot be
    judged against a dispatch cap — letting it run matches exactly what would have
    happened yesterday. This is reachable in production: evolution_watcher reads the
    estimate stored at ENQUEUE time, and the queue spans deployments.
    """
    Session = wdb
    called = {"ran": False}

    async def spy(spawn_id, **k):
        called["ran"] = True
        return {"proposal_id": None, "candidate_prompt": None,
                "gate": {"passed": False, "reason": "x", "aggregate": None}, "evidence": {}}
    monkeypatch.setattr(evolution_loop, "propose_improvement", spy)

    sid = await _spawn(Session)
    await _set_cap(Session, "1")            # a cap so low it would refuse anything judgeable
    aid = await _attempt(Session, sid, {
        "pairs": 16, "dispatches": 224, "judge_calls": 224, "est_tokens": 14374720,
        "lower_bound": True})               # the exact shape of the 10 rows in the wild
    await evolution_watcher._perform_attempt(aid, sid)

    assert called["ran"] is True, "an old-schema row was refused — behaviour regressed"
    assert await _outcome(Session, aid) != "skipped_budget"


async def test_a_NEW_schema_estimate_MISSING_the_key_is_refused(wdb, monkeypatch):
    """(B) The pair to the test above, and the whole point of the discriminator.

    `basis: "max"` says this estimate came from the new estimator, so `dispatches_max`
    must be there. Its absence is structural damage, and a spend gate that shrugs at
    structural damage fails OPEN — the same defect as last round's `int(None or 0) = 0`,
    which made a cap that could never be exceeded while still rendering a value in
    Settings.

    🔴 These two tests must BOTH exist. Either alone passes against an implementation
    that treats every missing key the same way, which is precisely the bug.
    """
    Session = wdb
    called = {"ran": False}

    async def spy(spawn_id, **k):
        called["ran"] = True
        return {"proposal_id": None, "candidate_prompt": None,
                "gate": {"passed": False, "reason": "x", "aggregate": None}, "evidence": {}}
    monkeypatch.setattr(evolution_loop, "propose_improvement", spy)

    sid = await _spawn(Session)
    await _set_cap(Session, "500")          # generous: refusal must come from the DAMAGE
    aid = await _attempt(Session, sid, {"basis": "max", "pairs": 16})   # key missing
    await evolution_watcher._perform_attempt(aid, sid)

    assert called["ran"] is False, "a structurally damaged estimate was allowed to spend"
    assert await _outcome(Session, aid) == "skipped_structural"


async def test_no_cap_set_means_neither_branch_fires(wdb, monkeypatch):
    """With no cap, even a damaged estimate runs: the gate is off, and inventing a refusal
    would be a cap nobody asked for."""
    Session = wdb
    called = {"ran": False}

    async def spy(spawn_id, **k):
        called["ran"] = True
        return {"proposal_id": None, "candidate_prompt": None,
                "gate": {"passed": False, "reason": "x", "aggregate": None}, "evidence": {}}
    monkeypatch.setattr(evolution_loop, "propose_improvement", spy)

    sid = await _spawn(Session)
    aid = await _attempt(Session, sid, {"basis": "max", "pairs": 16})
    await evolution_watcher._perform_attempt(aid, sid)

    assert called["ran"] is True
    assert await _outcome(Session, aid) != "skipped_structural"


async def test_a_legacy_token_cap_that_WAS_set_is_reported_not_dropped(client, monkeypatch):
    """🔴 The fail-loud path, exercised in the only state it exists for.

    Every other fixture leaves the legacy key unset, so `legacy_token_cap_dropped` is null
    everywhere and the reporting branch has never run. That makes the docstring's promise
    — "a limit that vanishes without a word is worse than one refused with an explanation"
    — a sentence nothing enforces. An install that HAD set a token cap is exactly whose
    limit is being dropped, and they are the ones who must be told.

    Asserted through the diagnostics endpoint, because that is where the value has to
    surface for a human to see it; a service-level check would pass while the payload
    dropped the key.
    """
    from server.db import session as db_session

    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    async with client.db_maker() as s:
        sp = Spawn(name="S", domain_category="g", system_prompt="p")
        s.add(sp)
        s.add(Setting(key="evolution_max_est_tokens", value="30000000"))
        await s.commit()
        sid = sp.id

    body = (await client.get(f"/api/v1/spawns/{sid}/evolution/diagnosis", headers=AUTH)).json()
    assert body["legacy_token_cap_dropped"] == "30000000", (
        "the removed cap's value must be reported back verbatim — a user who set 30M "
        "tokens needs to recognise their own number, not be told 'something was dropped'")
    # and the new cap really is absent, i.e. they are currently uncapped
    assert body["max_dispatches"] is None


async def test_each_attempt_starts_with_a_fresh_fetch_allowance(wdb, monkeypatch):
    """FU-2b's integration half, and the reason it exists as its own test.

    The allowance is per ATTEMPT, so somebody has to start it. Mutation showed
    the unit tests could not tell: they call reset_hermetic_fetch_budget()
    directly, so deleting the watcher's call left them all green while the
    counter became process-lifetime — first attempt after a restart gets the
    budget, every later one is refused on its first fetch. That reads as a
    broken feature rather than a limit.
    """
    from server.orchestrator import tool_loop

    Session = wdb

    async def spy(spawn_id, **k):
        return {"proposal_id": None, "candidate_prompt": None,
                "gate": {"passed": False, "reason": "x", "aggregate": None}, "evidence": {}}
    monkeypatch.setattr(evolution_loop, "propose_improvement", spy)

    # Spend the whole allowance, as a previous attempt would have.
    tool_loop.reset_hermetic_fetch_budget("evolution-eval")
    for _ in range(tool_loop.HERMETIC_FETCH_BUDGET):
        await tool_loop._check_fetch_budget(
            "web_search", conversation_id="evolution-eval", budget={})
    assert tool_loop.hermetic_fetches_used("evolution-eval") == tool_loop.HERMETIC_FETCH_BUDGET

    sid = await _spawn(Session)
    aid = await _attempt(Session, sid, {"basis": "max", "dispatches_max": 4})
    await evolution_watcher._perform_attempt(aid, sid)

    assert tool_loop.hermetic_fetches_used("evolution-eval") == 0, (
        "the new attempt inherited the previous attempt's spent allowance")
