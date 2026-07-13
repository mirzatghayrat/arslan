import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, EvolutionProposal, Spawn
from server.services import evolution_loop, optimizer, evaluator, replay_gate, replay_set


def _gate_result(passed):
    """A stub GateResult standing in for the paired ReplayGate final decision."""
    empty = {"wins": 0, "losses": 0, "ties": 0, "n": 0,
             "win_rate": 0.0, "p_value": 1.0, "ci95": [0.0, 0.0]}
    real = {"wins": 11, "losses": 0, "ties": 0, "n": 11,
            "win_rate": 1.0, "p_value": 0.0004, "ci95": [0.7, 1.0]}
    return replay_gate.GateResult(
        passed=passed, reason=("pass" if passed else "holdout_winrate"), flags=[],
        real_delta=(real if passed else empty), synthetic_delta=dict(empty),
        evidence_tier=("strong" if passed else "weak"), pairs=[],
        excluded_count=0, protected_run_ids=[101, 102])


def _patch_gate(monkeypatch, *, passed):
    """Stub the FINAL run_gate so the loop's certifying decision is deterministic.
    build_corpus is stubbed by _patch_common (the loop now builds the corpus once, up front,
    and reuses it for the gate), so this only fixes the gate verdict."""
    async def fake_run_gate(db, *, spawn_id, candidate_prompt, baseline_prompt, corpus,
                            persona="", changed_fields=None, excluded=0):
        return _gate_result(passed)
    monkeypatch.setattr(replay_gate, "run_gate", fake_run_gate)


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


async def _spawn(Session, prompt="ORIGINAL"):
    async with Session() as db:
        s = Spawn(name="S", domain_category="x", system_prompt=prompt, generation_level=1, config={})
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


# ── multi-epoch propose_improvement tests ────────────────────────────────────


class _Spawn:
    id = 1
    name = "fin"
    persona_role = "analyst"
    persona_tone = "terse"
    system_prompt = "## Role\nYou are an analyst."


async def _seed_spawn(Session, spawn_like):
    """Insert a real Spawn row (id=1 in the fresh in-memory DB) mirroring spawn_like."""
    async with Session() as db:
        s = Spawn(name=spawn_like.name, domain_category="x",
                  persona_role=spawn_like.persona_role, persona_tone=spawn_like.persona_tone,
                  system_prompt=spawn_like.system_prompt, generation_level=1, config={})
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


def _corpus(*, propose_n=3, holdout_n=2):
    """A ReplayGate corpus with a known propose/holdout partition. The optimizer must only
    ever see the PROPOSE tasks; the holdout tasks (source_run_id 200+) certify the gate."""
    c = replay_gate.Corpus()
    for i in range(propose_n):
        c.append({"task": f"p{i}", "corpus_label": "real", "source_ref": 100 + i,
                  "source_run_id": 100 + i, "split_side": "propose"})
    for i in range(holdout_n):
        c.append({"task": f"h{i}", "corpus_label": "real", "source_ref": 200 + i,
                  "source_run_id": 200 + i, "split_side": "holdout"})
    return c


def _rich(propose_n=3):
    """Stored judge evidence for the propose real runs (joined by run id in the loop)."""
    return [{"run_id": 100 + i, "task": f"p{i}", "baseline_output": f"b{i}",
             "baseline_overall": 6, "baseline_dims": {}} for i in range(propose_n)]


def _patch_common(monkeypatch, *, edits_by_epoch, corpus=None, rich=None):
    the_corpus = corpus if corpus is not None else _corpus()
    async def fake_corpus(db, spawn_id, *, baseline_started_at=None, mint=False): return the_corpus
    monkeypatch.setattr(replay_gate, "build_corpus", fake_corpus)
    async def fake_build(spawn_id, **k): return rich if rich is not None else _rich()
    monkeypatch.setattr(replay_set, "build", fake_build)
    async def fake_val_outputs(spawn_id, doc, val): return {it["run_id"]: "best" for it in val}
    monkeypatch.setattr(evolution_loop, "_val_outputs", fake_val_outputs)
    seq = list(edits_by_epoch)
    seen_avoid = []
    async def fake_edits(spawn, train, *, lr_budget, avoid):
        seen_avoid.append(list(avoid))
        return seq.pop(0) if seq else []
    monkeypatch.setattr(optimizer, "propose_edits", fake_edits)
    return seen_avoid


async def test_loop_accepts_improving_edit_and_proposes(monkeypatch, memdb):
    _patch_common(monkeypatch,
                  edits_by_epoch=[[{"op": "add", "section": "Style", "content": "Be terse."}], []])
    async def fake_eval(*, spawn_id, persona, candidate_prompt, replay_items, scorer=None, baseline_outputs=None):
        better = "Be terse." in candidate_prompt
        o = {"better": 1, "worse": 0, "tie": 0} if better else {"better": 0, "worse": 0, "tie": 1}
        return {"items": [], "aggregate": {"overall": o, "dims": {}},
                "gate": {"passed": better, "reason": "", "aggregate": {"overall": o, "dims": {}}}}
    monkeypatch.setattr(evaluator, "evaluate", fake_eval)
    _patch_gate(monkeypatch, passed=True)          # ReplayGate passes on holdout
    await _seed_spawn(memdb, _Spawn)
    res = await evolution_loop.propose_improvement(1, epochs=2)
    assert res["proposal_id"] is not None
    assert res["gate"]["passed"] is True
    assert res["evidence"]["diff"] == [{"op": "add", "section": "Style", "content": "Be terse."}]
    # The persisted proposal is a LIVING one: status='open', base_prompt_sha pinned,
    # gate evidence (protected_run_ids) carried on it for E2's redact exemption.
    async with memdb() as db:
        prop = await db.get(EvolutionProposal, res["proposal_id"])
    assert prop.status == "open"
    assert prop.base_prompt_sha and len(prop.base_prompt_sha) == 64
    assert prop.evidence["protected_run_ids"] == [101, 102]
    assert "real_delta" in prop.evidence and "synthetic_delta" in prop.evidence


async def test_loop_rejects_and_buffers(monkeypatch, memdb):
    seen_avoid = _patch_common(monkeypatch,
                               edits_by_epoch=[[{"op": "add", "section": "X", "content": "bad"}],
                                               [{"op": "add", "section": "Y", "content": "also"}]])
    async def fake_eval(*, spawn_id, persona, candidate_prompt, replay_items, scorer=None, baseline_outputs=None):
        o = {"better": 0, "worse": 0, "tie": 1}
        return {"items": [], "aggregate": {"overall": o, "dims": {}},
                "gate": {"passed": False, "reason": "", "aggregate": {"overall": o, "dims": {}}}}
    monkeypatch.setattr(evaluator, "evaluate", fake_eval)
    await _seed_spawn(memdb, _Spawn)
    res = await evolution_loop.propose_improvement(1, epochs=2)
    assert res["proposal_id"] is None
    assert {"op": "add", "section": "X", "content": "bad"} in seen_avoid[1]  # rejected edit buffered into next epoch


async def test_loop_no_op_on_insufficient(monkeypatch, memdb):
    async def fake_corpus(db, spawn_id, *, baseline_started_at=None, mint=False):
        return replay_gate.Corpus()
    monkeypatch.setattr(replay_gate, "build_corpus", fake_corpus)
    async def fake_build(spawn_id, **k): return []
    monkeypatch.setattr(replay_set, "build", fake_build)
    await _seed_spawn(memdb, _Spawn)
    res = await evolution_loop.propose_improvement(1, epochs=2)
    assert res["proposal_id"] is None and res["gate"]["passed"] is False
    assert res["gate"]["reason"] == "insufficient scored runs"


async def test_propose_improvement_builds_corpus_with_mint_true(monkeypatch, memdb):
    # E9-b: the REAL evolution path must build its corpus with mint=True so a thin holdout is
    # topped up to the gate floor — unlike the read-only cost preview (evolution_estimate), which
    # passes mint=False and never mutates. Spy the exact mint kwarg propose_improvement passes.
    _patch_common(monkeypatch, edits_by_epoch=[[]])   # sets up replay_set/optimizer/eval stubs
    captured = {}

    async def spy_corpus(db, spawn_id, *, baseline_started_at=None, mint=False):
        captured["mint"] = mint
        return _corpus()

    monkeypatch.setattr(replay_gate, "build_corpus", spy_corpus)   # override _patch_common's
    _patch_gate(monkeypatch, passed=True)
    await _seed_spawn(memdb, _Spawn)
    await evolution_loop.propose_improvement(1, epochs=1)
    assert captured["mint"] is True


async def test_loop_final_gate_fails_on_holdout(monkeypatch, memdb):
    # An edit is accepted against the running-best propose signal, but the paired
    # ReplayGate FAILS on holdout → no proposal (the gate, not the optimizer, decides).
    _patch_common(monkeypatch,
                  edits_by_epoch=[[{"op": "add", "section": "Style", "content": "Be terse."}], []])
    async def fake_eval(*, spawn_id, persona, candidate_prompt, replay_items, scorer=None, baseline_outputs=None):
        better = "Be terse." in candidate_prompt
        o = {"better": 1, "worse": 0, "tie": 0} if better else {"better": 0, "worse": 0, "tie": 1}
        return {"items": [], "aggregate": {"overall": o, "dims": {}},
                "gate": {"passed": better, "reason": "", "aggregate": {"overall": o, "dims": {}}}}
    monkeypatch.setattr(evaluator, "evaluate", fake_eval)
    _patch_gate(monkeypatch, passed=False)         # ReplayGate FAILS on holdout
    await _seed_spawn(memdb, _Spawn)
    res = await evolution_loop.propose_improvement(1, epochs=2)
    assert res["proposal_id"] is None
    assert res["gate"]["passed"] is False and res["gate"]["reason"] == "holdout_winrate"


async def test_loop_degrades_on_dispatch_failure(monkeypatch, memdb):
    _patch_common(monkeypatch, edits_by_epoch=[[{"op": "add", "section": "X", "content": "c"}]])
    async def boom(spawn_id, doc, val): raise RuntimeError("dispatch down")
    monkeypatch.setattr(evolution_loop, "_val_outputs", boom)
    await _seed_spawn(memdb, _Spawn)
    res = await evolution_loop.propose_improvement(1, epochs=2)  # must not raise
    assert res["proposal_id"] is None


async def test_inner_loop_rejects_overlength_edit_without_judging(monkeypatch, memdb):
    # E9-b: an edit whose applied doc would exceed _length_ceiling(original) must be rejected in
    # the optimizer inner loop WITHOUT calling evaluator.evaluate (bounded by construction — the
    # candidate can never reach the final holdout gate only to blow the length cap).
    from server.services import skill_doc
    evaluated = {"n": 0}
    big = "x" * 3000                                     # one huge added section
    _patch_common(monkeypatch,
                  edits_by_epoch=[[{"op": "add", "section": "Bloat", "content": big}], []])

    async def boom_eval(**k):
        evaluated["n"] += 1
        raise AssertionError("must not evaluate an over-length candidate")
    monkeypatch.setattr(evaluator, "evaluate", boom_eval)
    await _seed_spawn(memdb, _Spawn)
    # sanity: the applied candidate really does exceed the ceiling for this short baseline
    original = skill_doc.apply_edits(_Spawn.system_prompt, [])
    cand = skill_doc.apply_edits(original, [{"op": "add", "section": "Bloat", "content": big}])
    assert len(cand) > replay_gate._length_ceiling(original)
    res = await evolution_loop.propose_improvement(1, epochs=2)
    assert res["proposal_id"] is None                    # nothing accepted
    assert evaluated["n"] == 0                            # never judged
    assert res["gate"]["reason"] == "no accepted edit beats the original"


# ── confirm_proposal tests (unchanged behavior) ──────────────────────────────


async def test_confirm_promotes_when_gate_passed(memdb, monkeypatch):
    sid = await _spawn(memdb, prompt="ORIGINAL")
    async with memdb() as db:
        p = EvolutionProposal(spawn_id=sid, candidate_prompt="NEWP", gate_passed=True,
                              evidence={}, status="proposed")
        db.add(p)
        await db.commit()
        await db.refresh(p)
        pid = p.id

    res = await evolution_loop.confirm_proposal(pid)
    assert res["ok"] is True
    async with memdb() as db:
        s = await db.get(Spawn, sid)
        p = await db.get(EvolutionProposal, pid)
    assert s.system_prompt == "NEWP"
    assert s.generation_level == 2
    assert s.config["prompt_history"][0]["old_prompt"] == "ORIGINAL"
    assert p.status == "promoted"


async def test_confirm_refuses_when_gate_failed(memdb, monkeypatch):
    sid = await _spawn(memdb, prompt="ORIGINAL")
    async with memdb() as db:
        p = EvolutionProposal(spawn_id=sid, candidate_prompt="NEWP", gate_passed=False,
                              evidence={}, status="proposed")
        db.add(p)
        await db.commit()
        await db.refresh(p)
        pid = p.id
    res = await evolution_loop.confirm_proposal(pid)
    assert res["ok"] is False
    async with memdb() as db:
        s = await db.get(Spawn, sid)
    assert s.system_prompt == "ORIGINAL"


async def test_confirm_refuses_stale(memdb, monkeypatch):
    # A stale living proposal (base prompt drifted) must never be promoted — confirm refuses
    # with an 'already stale' reason (the API maps this to 409).
    sid = await _spawn(memdb, prompt="ORIGINAL")
    async with memdb() as db:
        p = EvolutionProposal(spawn_id=sid, candidate_prompt="NEWP", gate_passed=True,
                              evidence={}, status="stale")
        db.add(p)
        await db.commit()
        await db.refresh(p)
        pid = p.id
    res = await evolution_loop.confirm_proposal(pid)
    assert res["ok"] is False
    assert "stale" in res["reason"]
    async with memdb() as db:
        s = await db.get(Spawn, sid)
    assert s.system_prompt == "ORIGINAL"   # not promoted


async def test_confirm_refuses_when_base_prompt_drifted(memdb, monkeypatch):
    # FIX 2 (spec §E7 audit #14): an OPEN proposal whose gate ran against a baseline that has
    # since drifted (another proposal for the same spawn was promoted first) must NOT be
    # promoted — that would silently revert the earlier change against a baseline that no
    # longer exists. confirm re-checks base_prompt_sha, refuses, and marks the proposal stale.
    from server.services import skill_doc
    sid = await _spawn(memdb, prompt="ORIGINAL")
    base_sha = evolution_loop._sha(skill_doc.apply_edits("ORIGINAL", []))
    async with memdb() as db:
        a = EvolutionProposal(spawn_id=sid, candidate_prompt="PROMPT_A", gate_passed=True,
                              evidence={}, status="open", base_prompt_sha=base_sha)
        b = EvolutionProposal(spawn_id=sid, candidate_prompt="PROMPT_B", gate_passed=True,
                              evidence={}, status="open", base_prompt_sha=base_sha)
        db.add_all([a, b])
        await db.commit()
        await db.refresh(a)
        await db.refresh(b)
        aid, bid = a.id, b.id

    first = await evolution_loop.confirm_proposal(aid)     # promote A → spawn prompt drifts
    assert first["ok"] is True

    second = await evolution_loop.confirm_proposal(bid)    # B is now stale vs the live prompt
    assert second["ok"] is False
    assert "stale" in second["reason"]
    async with memdb() as db:
        s = await db.get(Spawn, sid)
        pb = await db.get(EvolutionProposal, bid)
    assert s.system_prompt == "PROMPT_A"   # B did NOT overwrite A's promotion
    assert pb.status == "stale"


async def test_confirm_twice_is_noop(memdb, monkeypatch):
    sid = await _spawn(memdb, prompt="ORIGINAL")
    async with memdb() as db:
        p = EvolutionProposal(spawn_id=sid, candidate_prompt="NEWP", gate_passed=True,
                              evidence={}, status="proposed")
        db.add(p)
        await db.commit()
        await db.refresh(p)
        pid = p.id

    first = await evolution_loop.confirm_proposal(pid)
    assert first["ok"] is True
    second = await evolution_loop.confirm_proposal(pid)
    assert second["ok"] is False
    assert "already" in second["reason"]

    # spawn promoted exactly once: generation_level bumped to 2 (not 3)
    async with memdb() as db:
        s = await db.get(Spawn, sid)
    assert s.generation_level == 2
