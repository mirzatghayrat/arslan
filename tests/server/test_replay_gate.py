"""ReplayGate math + holdout discipline (S2 E4, the methodology core).

All tests STUB the replay arms (replay_run.run_arm / snapshot_ambient) and the judge
(compare_judge.compare) so they exercise the GATE MATH deterministically — not real LLM
behavior. The two CRITICAL regressions (C1, C3) are named exactly as the user will verify.
"""
import itertools

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base, Run, RunStep, SyntheticTask
from server.services import binom, compare_judge, replay_gate, replay_run
from server.services.replay_gate import DIMENSIONS, HoldoutViolation, run_gate

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ── stubs ────────────────────────────────────────────────────────────────────────────

def _pt(corpus_label, split_side, idx, verdict="tie", ps=False, dims=None):
    """A corpus pairtask carrying the DESIRED per-pair verdict for the stub judge to echo."""
    return {
        "task": f"{corpus_label}-{split_side}-{idx}",
        "corpus_label": corpus_label,
        "split_side": split_side,
        "source_ref": idx,
        "_verdict": verdict,
        "_ps": ps,
        "_dims": dims or {d: verdict for d in DIMENSIONS},
    }


def _stub_arms(monkeypatch, *, base_len=10, cand_len=10):
    counter = itertools.count(1)

    async def fake_snapshot(db, *, spawn_id, conversation_id, task=""):
        return {"facts": "", "kb_block": "", "kb_sources": None}

    async def fake_run_arm(db, *, spawn_id, task, system_prompt, ambient, conversation_id=None):
        n = cand_len if system_prompt == _CAND else base_len
        return {"run_id": next(counter), "output": "o" * n, "evidence": ""}

    monkeypatch.setattr(replay_run, "snapshot_ambient", fake_snapshot)
    monkeypatch.setattr(replay_run, "run_arm", fake_run_arm)


def _stub_judge(monkeypatch):
    async def fake_compare(*, task, persona, output_a, output_b,
                           evidence_a="", evidence_b="", item=None):
        v = (item or {}).get("_verdict", "tie")
        dims = (item or {}).get("_dims") or {d: v for d in DIMENSIONS}
        return {"dimensions": dims, "overall": v, "margin": 0.0,
                "position_sensitive": (item or {}).get("_ps", False), "reason": ""}

    monkeypatch.setattr(compare_judge, "compare", fake_compare)


_BASE = "BASELINE PROMPT"
_CAND = "CANDIDATE PROMPT"


async def _gate(corpus, monkeypatch, *, base_len=10, cand_len=10, candidate=_CAND, baseline=_BASE):
    _stub_arms(monkeypatch, base_len=base_len, cand_len=cand_len)
    _stub_judge(monkeypatch)
    return await run_gate(None, spawn_id=1, candidate_prompt=candidate,
                          baseline_prompt=baseline, corpus=corpus, persona="p")


# ── CRITICAL: C1 — decided on holdout, not the winning propose set ─────────────────────

async def test_C1_propose_wins_holdout_loses_fails_gate(monkeypatch):
    # ALL propose pairs = candidate WIN; ALL holdout pairs = candidate LOSS.
    corpus = ([_pt("real", "propose", i, "b") for i in range(6)]
              + [_pt("real", "holdout", 100 + i, "a") for i in range(12)])
    res = await _gate(corpus, monkeypatch)
    assert res.passed is False
    # The gate is decided on holdout (all losses) — NOT the propose set (all wins).
    assert "holdout" in res.reason or "winrate" in res.reason or "insufficient" in res.reason
    # Propose wins are quarantined to the internal signal, never the verdict.
    assert res.real_delta["wins"] == 0 and res.real_delta["losses"] == 12


# ── CRITICAL: C3 — synthetic wins cannot carry a real-task regression ──────────────────

async def test_C3_synthetic_wins_real_regresses_fails_gate(monkeypatch):
    # Holdout = 9 synthetic (candidate wins) + 4 real (candidate 1W / 3L).
    corpus = ([_pt("synthetic", "holdout", i, "b") for i in range(9)]
              + [_pt("real", "holdout", 200, "b")]
              + [_pt("real", "holdout", 300 + i, "a") for i in range(3)])
    res = await _gate(corpus, monkeypatch)
    assert res.passed is False
    assert res.reason == "real_floor"
    # Synthetic looked great; real regressed — and real is what gates.
    assert res.synthetic_delta["wins"] == 9 and res.synthetic_delta["losses"] == 0
    assert res.real_delta["wins"] == 1 and res.real_delta["losses"] == 3


# ── holdout discipline is real code ────────────────────────────────────────────────────

async def test_HoldoutViolation_on_propose_delta():
    propose_pairs = [{"split_side": "propose", "overall": "b",
                      "per_dim": {d: "b" for d in DIMENSIONS}, "task_hash": "x"}]
    with pytest.raises(HoldoutViolation):
        replay_gate.compute_delta(propose_pairs)


async def test_no_merged_delta_field(monkeypatch):
    corpus = [_pt("real", "holdout", i, "b") for i in range(12)]
    res = await _gate(corpus, monkeypatch)
    uf = res.user_facing()
    assert "real_delta" in uf and "synthetic_delta" in uf
    for banned in ("combined_delta", "merged_delta", "overall_delta", "delta",
                   "win_rate", "combined", "aggregate_delta"):
        assert banned not in uf
    # The dataclass itself exposes only the two separate deltas.
    import dataclasses
    fields = {f.name for f in dataclasses.fields(replay_gate.GateResult)}
    assert "real_delta" in fields and "synthetic_delta" in fields
    assert not any("combined" in f or f in ("delta", "merged_delta") for f in fields)


async def test_internal_signal_is_propose_only(monkeypatch):
    corpus = ([_pt("real", "propose", i, "b") for i in range(5)]
              + [_pt("real", "holdout", 100 + i, "b") for i in range(12)])
    res = await _gate(corpus, monkeypatch)
    sig = res.internal_signal()          # propose-only aggregate (never rendered)
    assert sig["wins"] == 5 and sig["n"] == 5
    # user_facing carries ONLY holdout pairs.
    assert all(p["split_side"] == "holdout" for p in res.user_facing()["pairs"])


# ── thresholds ─────────────────────────────────────────────────────────────────────────

async def test_insufficient_holdout(monkeypatch):
    corpus = [_pt("real", "holdout", i, "b") for i in range(9)]   # 9 < 10
    res = await _gate(corpus, monkeypatch)
    assert res.passed is False and res.reason == "insufficient_holdout"


async def test_length_cap_fails_before_judging(monkeypatch):
    # Candidate > 1.25x baseline → fail BEFORE any arm/judge is called.
    called = {"arms": 0}

    async def boom(*a, **k):
        called["arms"] += 1
        raise AssertionError("should not run arms when length cap trips")

    monkeypatch.setattr(replay_run, "run_arm", boom)
    monkeypatch.setattr(replay_run, "snapshot_ambient", boom)
    res = await run_gate(None, spawn_id=1, candidate_prompt="x" * 100,
                         baseline_prompt="x" * 10,
                         corpus=[_pt("real", "holdout", 0, "b")], persona="p")
    assert res.passed is False and res.reason == "length_cap"
    assert called["arms"] == 0


async def test_length_cap_absolute_12000(monkeypatch):
    res = await run_gate(None, spawn_id=1, candidate_prompt="x" * 12001,
                         baseline_prompt="x" * 12001, corpus=[], persona="p")
    assert res.passed is False and res.reason == "length_cap"


async def test_verbose_fail_and_warn(monkeypatch):
    corpus = [_pt("real", "holdout", i, "b") for i in range(12)]
    # ratio 3.0 > 2.0 → fail
    res = await _gate(corpus, monkeypatch, base_len=10, cand_len=30)
    assert res.passed is False and res.reason == "verbose_fail"
    # ratio 1.6 (1.5<r<=2.0) → warn only, still passes
    res2 = await _gate(corpus, monkeypatch, base_len=10, cand_len=16)
    assert res2.passed is True and "verbose_warn" in res2.flags


async def test_per_dim_regression_fails(monkeypatch):
    # Overall wins (>=60%) but the 'identity' dimension regresses.
    win = {"fabrication": "b", "identity": "b", "completion": "b"}
    reg = {"fabrication": "b", "identity": "a", "completion": "b"}
    # identity: 5 wins vs 7 losses → losses > wins → regression (overall stays 'b' for all).
    corpus = ([_pt("real", "holdout", i, "b", dims=win) for i in range(5)]
              + [_pt("real", "holdout", 100 + i, "b", dims=reg) for i in range(7)])
    res = await _gate(corpus, monkeypatch)
    assert res.passed is False and res.reason == "dim_regressed:identity"


async def test_synthetic_driven_flag_when_few_real(monkeypatch):
    # 12 synthetic holdout wins, only 2 real → N_real<3 → flag synthetic_driven, still passes.
    corpus = ([_pt("synthetic", "holdout", i, "b") for i in range(12)]
              + [_pt("real", "holdout", 100 + i, "b") for i in range(2)])
    res = await _gate(corpus, monkeypatch)
    assert res.passed is True
    assert "synthetic_driven" in res.flags


async def test_real_floor_passes_when_real_holds(monkeypatch):
    # 9 synthetic wins + 4 real (3W/1L) → real win-rate 0.75 >= 0.50 → passes.
    corpus = ([_pt("synthetic", "holdout", i, "b") for i in range(9)]
              + [_pt("real", "holdout", 200 + i, "b") for i in range(3)]
              + [_pt("real", "holdout", 300, "a")])
    res = await _gate(corpus, monkeypatch)
    assert res.passed is True
    assert res.real_delta["win_rate"] == 0.75


async def test_position_sensitive_flag(monkeypatch):
    # >40% of holdout pairs position-sensitive → low_confidence flag.
    corpus = ([_pt("real", "holdout", i, "b", ps=True) for i in range(6)]
              + [_pt("real", "holdout", 100 + i, "b", ps=False) for i in range(6)])
    res = await _gate(corpus, monkeypatch)
    assert "low_confidence" in res.flags


async def test_evidence_tier_boundaries(monkeypatch):
    # 10/10 wins → p≈0.000977 < 0.05 → strong
    strong = await _gate([_pt("real", "holdout", i, "b") for i in range(10)], monkeypatch)
    assert strong.evidence_tier == "strong"
    # 8 wins / 2 losses (n=10) → p≈0.0547 in (0.05,0.2] → medium
    medium = await _gate(
        [_pt("real", "holdout", i, "b") for i in range(8)]
        + [_pt("real", "holdout", 100 + i, "a") for i in range(2)], monkeypatch)
    assert medium.evidence_tier == "medium"
    # 6 wins / 4 losses (n=10) → p≈0.377 > 0.2 → weak (also fails winrate, tier still weak)
    weak = await _gate(
        [_pt("real", "holdout", i, "b") for i in range(6)]
        + [_pt("real", "holdout", 100 + i, "a") for i in range(4)], monkeypatch)
    assert weak.evidence_tier == "weak"


# ── FIX 4a: effective-N dedupe of correlated trials (a real task + its variants = 1 trial) ──

def test_effective_counts_collapses_variants():
    from server.services.replay_gate import _effective_counts
    # a real task R + 2 synthetic variants of R (same source_run_id), all candidate wins:
    # correlated → ONE effective win over N=1 (not 3).
    pairs = [
        {"overall": "b", "source_run_id": 42, "task_hash": "r"},
        {"overall": "b", "source_run_id": 42, "task_hash": "v1"},
        {"overall": "b", "source_run_id": 42, "task_hash": "v2"},
    ]
    assert _effective_counts(pairs) == (1, 1)
    # + one independent real win (own root) + one domain synth win (source_run_id=None):
    # now 3 effective wins over N=3 (raw would be 5).
    pairs += [
        {"overall": "b", "source_run_id": 7, "task_hash": "x"},
        {"overall": "b", "source_run_id": None, "task_hash": "domain"},
    ]
    assert _effective_counts(pairs) == (3, 3)
    # a split group (2 win / 1 loss on the same root) collapses to ONE win by majority.
    split = [
        {"overall": "b", "source_run_id": 9, "task_hash": "a"},
        {"overall": "b", "source_run_id": 9, "task_hash": "b"},
        {"overall": "a", "source_run_id": 9, "task_hash": "c"},
    ]
    assert _effective_counts(split) == (1, 1)


async def test_effective_n_dedupes_variant_p_value(monkeypatch):
    # 2 synthetic variants of the SAME real source (source_run_id=42), both candidate wins.
    # RAW counts stay honest (wins=2, n=2) but the p-value must use the EFFECTIVE N=1 so
    # correlated variants can't manufacture significance.
    corpus = [
        {"task": "v0", "corpus_label": "synthetic", "split_side": "holdout",
         "source_ref": {"synth_id": 1, "version": 1}, "source_run_id": 42,
         "_verdict": "b", "_dims": {d: "b" for d in DIMENSIONS}, "_ps": False},
        {"task": "v1", "corpus_label": "synthetic", "split_side": "holdout",
         "source_ref": {"synth_id": 2, "version": 1}, "source_run_id": 42,
         "_verdict": "b", "_dims": {d: "b" for d in DIMENSIONS}, "_ps": False},
    ]
    res = await _gate(corpus, monkeypatch)
    sd = res.synthetic_delta
    assert sd["wins"] == 2 and sd["losses"] == 0 and sd["n"] == 2   # raw counts unchanged
    assert sd["effective_n"] == 1                                    # collapsed to one trial
    assert sd["p_value"] == binom.p_value(1, 1)                      # p uses the SMALLER N
    assert sd["p_value"] != binom.p_value(2, 2)                      # not the inflated raw p


async def test_effective_n_dedupes_variants_in_combined_tier(monkeypatch):
    # 1 real task R + 2 variants of R (all wins) + 9 independent real wins.
    # Raw combined N = 12; effective N = 10 (the 3 correlated pairs collapse to 1 trial).
    def _v(label, tid, srid):
        return {"task": tid, "corpus_label": label, "split_side": "holdout",
                "source_ref": srid, "source_run_id": srid,
                "_verdict": "b", "_dims": {d: "b" for d in DIMENSIONS}, "_ps": False}
    corpus = ([_v("real", "R", 500)]
              + [_v("synthetic", f"var{i}", 500) for i in range(2)]
              + [_v("real", f"i{i}", 600 + i) for i in range(9)])
    res = await _gate(corpus, monkeypatch)
    from server.services.replay_gate import _effective_counts, _tier
    # the collapsed count is 10 (1 group + 9 independent), and the tier is computed on it.
    assert _effective_counts(res.pairs) == (10, 10)
    assert res.evidence_tier == _tier(binom.p_value(10, 10))
    # the real corpus displays raw honest counts (10 real pairs: R + 9 independent).
    assert res.real_delta["wins"] == 10 and res.real_delta["n"] == 10


async def test_tier_exact_boundaries():
    from server.services.replay_gate import _tier
    assert _tier(0.04) == "strong"
    assert _tier(0.05) == "medium"      # 0.05 inclusive → medium
    assert _tier(0.20) == "medium"      # 0.20 inclusive → medium
    assert _tier(0.21) == "weak"


async def test_gate_passes_clean_candidate(monkeypatch):
    corpus = [_pt("real", "holdout", i, "b") for i in range(11)]
    res = await _gate(corpus, monkeypatch)
    assert res.passed is True and res.reason == "pass"
    assert res.protected_run_ids and len(res.protected_run_ids) == 22   # 11 pairs × 2 arms
    assert res.real_delta["p_value"] == binom.p_value(11, 11)


# ── routing trigger (gate 8) ───────────────────────────────────────────────────────────

def test_routing_not_triggered_for_prompt_only():
    # system_prompt is NOT a routing-consumed field → gate 8 skipped.
    assert replay_gate.routing_triggered({"system_prompt"}) is False
    assert replay_gate.routing_triggered(None) is False


def test_routing_triggered_for_metadata_fields():
    assert replay_gate.routing_triggered({"capabilities"}) is True
    assert replay_gate.routing_triggered({"domain_category"}) is True
    assert replay_gate.routing_triggered({"persona_role", "system_prompt"}) is True


async def test_prompt_change_does_not_flag_routing(monkeypatch):
    corpus = [_pt("real", "holdout", i, "b") for i in range(11)]
    res = await _gate(corpus, monkeypatch)
    assert "routing_uncheckable" not in res.flags


# ── deterministic split + build_corpus ─────────────────────────────────────────────────

def test_split_side_deterministic():
    from server.services.replay_gate import _split_side
    for task in ("alpha", "beta task", "写一个分析", "task-42"):
        first = _split_side(7, task)
        assert first in ("propose", "holdout")
        assert all(_split_side(7, task) == first for _ in range(5))   # stable
    # different spawn_id can move a task to the other side (keyed on both)
    sides = {_split_side(sid, "same-task") for sid in range(50)}
    assert sides == {"propose", "holdout"}   # both sides represented across spawns


def test_split_side_covers_both_sides():
    from server.services.replay_gate import _split_side
    sides = {_split_side(1, f"task-{i}") for i in range(200)}
    assert sides == {"propose", "holdout"}


@pytest.fixture
async def memdb(monkeypatch):
    from server.db import session as db_session
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


async def test_build_corpus_mixes_real_and_synthetic(memdb):
    from datetime import datetime
    async with memdb() as db:
        # real: a clean live epoch=1 scored run with NO tool_call steps → replayable
        r1 = Run(conversation_id="c", spawn_id=1, user_message="real task 1",
                 status="scored", kind="live", epoch=1, created_at=datetime(2026, 7, 1))
        # excluded: a run that used an MCP tool → not replayable
        r2 = Run(conversation_id="c", spawn_id=1, user_message="real task 2",
                 status="scored", kind="live", epoch=1, created_at=datetime(2026, 7, 1))
        # excluded by epoch: pre-baseline epoch=0
        r3 = Run(conversation_id="c", spawn_id=1, user_message="old task",
                 status="scored", kind="live", epoch=0, created_at=datetime(2026, 7, 1))
        db.add_all([r1, r2, r3])
        await db.commit()
        await db.refresh(r2)
        db.add(RunStep(run_id=r2.id, seq=0, kind="tool_call",
                       ref={"tool": "mcp_x__do"}, detail={}))
        db.add_all([
            SyntheticTask(spawn_id=1, version=2, task="synth propose", source="domain",
                          split_side="propose", status="active"),
            SyntheticTask(spawn_id=1, version=2, task="synth holdout", source="domain",
                          split_side="holdout", status="active"),
            # old version — must be ignored
            SyntheticTask(spawn_id=1, version=1, task="old synth", source="domain",
                          split_side="propose", status="active"),
        ])
        await db.commit()

    async with memdb() as db:
        corpus = await replay_gate.build_corpus(db, 1)

    labels = [(c["corpus_label"], c["task"]) for c in corpus]
    assert ("real", "real task 1") in labels
    assert ("real", "real task 2") not in labels        # excluded: MCP tool
    assert ("real", "old task") not in labels           # excluded: epoch=0
    assert ("synthetic", "synth propose") in labels
    assert ("synthetic", "synth holdout") in labels
    assert ("synthetic", "old synth") not in labels     # excluded: stale version
    # synthetic split_side comes from the stored row (never re-hashed).
    synth = {c["task"]: c["split_side"] for c in corpus if c["corpus_label"] == "synthetic"}
    assert synth == {"synth propose": "propose", "synth holdout": "holdout"}
    assert corpus.excluded == 1                          # r2 dropped as non-replayable


async def test_build_corpus_baseline_started_at_filter(memdb):
    from datetime import datetime
    async with memdb() as db:
        db.add_all([
            Run(conversation_id="c", spawn_id=1, user_message="before baseline",
                status="scored", kind="live", epoch=1, created_at=datetime(2026, 6, 1)),
            Run(conversation_id="c", spawn_id=1, user_message="after baseline",
                status="scored", kind="live", epoch=1, created_at=datetime(2026, 7, 5)),
        ])
        await db.commit()

    async with memdb() as db:
        corpus = await replay_gate.build_corpus(
            db, 1, baseline_started_at=datetime(2026, 7, 1))
    tasks = [c["task"] for c in corpus]
    assert "after baseline" in tasks
    assert "before baseline" not in tasks   # created before baseline_started_at → excluded
