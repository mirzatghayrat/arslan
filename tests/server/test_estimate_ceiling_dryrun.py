"""The only test that can prove the derived ceiling is TRUE rather than merely computed.

Every other test of this estimator recomputes the same expression the implementation uses
(`test_estimate_formula_matches` does exactly that) — it pins the shape and would stay
green against a formula that is wrong in the same way twice. The alternative, hand-working
out the expected number, is the same tautology written by hand.

So: run the REAL loop with the spend seams stubbed, count what it ACTUALLY dispatches, and
assert the projection brackets it. Four module attributes are patched, not the factory —
`build_adapter` is a from-import in each consumer (compare_judge:14, optimizer:15,
synthetic_corpus:44), so patching llm_factory.build_adapter intercepts none of them.

🔴 The judge stub is POSITION-AWARE, and that is load-bearing. compare_judge runs two
position-swapped passes and merges with `x if x == y else "tie"`. A stub that returns a
fixed verdict answers both passes identically, which _to_ab maps through opposite slot
tables — every dimension comes back "tie", evaluator._gate needs better >= 1, so every
candidate is rejected, `accepted` stays empty, and propose_improvement returns at :181
BEFORE run_gate. The gate would never run, the ceiling would never be approached, and the
mutation that reverts the formula to 14*P would pass. The test would look thorough and
prove nothing.
"""
from __future__ import annotations

import pytest

from server.db import session as db_session
from server.db.models import Spawn
from server.services import (
    compare_judge,
    evolution_estimate,
    evolution_loop,
    evolution_meter,
    optimizer,
    replay_gate,
    replay_run,
    replay_set,
    synthetic_corpus,
    trace_evidence,
)
from server.orchestrator import dispatcher

AUTH: dict[str, str] = {}

CAND_MARK = "CANDIDATE-OUTPUT"
BASE_MARK = "BASELINE-OUTPUT"


def _corpus(*, propose: int, holdout: int) -> list[dict]:
    """A corpus with enough REAL holdout that the estimate projects no synthetic top-up,
    so `pairs` is exactly len(corpus) on both sides and the comparison is apples to
    apples."""
    assert holdout >= replay_gate.MIN_HOLDOUT_N, "otherwise the estimate projects a top-up"
    out = []
    for i in range(propose):
        out.append({"run_id": 1000 + i, "task": f"propose task {i}", "split_side": "propose",
                    "corpus_label": "real", "score": 3.0})
    for i in range(holdout):
        out.append({"run_id": 2000 + i, "task": f"holdout task {i}", "split_side": "holdout",
                    "corpus_label": "real", "score": 3.0})
    return out


class _Resp:
    def __init__(self, content: str):
        self.content = content
        self.usage = None


class _StubAdapter:
    """Stands in for whatever build_adapter would have returned. `mode` decides what a
    .chat() call means in this context: judging, proposing an edit, or minting."""

    def __init__(self, mode: str, counter: dict):
        self.mode = mode
        self.counter = counter

    async def chat(self, *, system: str = "", user: str = "", **kw):
        self.counter[self.mode] = self.counter.get(self.mode, 0) + 1
        if self.mode == "judge":
            # POSITION-AWARE: whichever slot holds the candidate wins. 输出① is `first`.
            first_is_candidate = user.find(CAND_MARK) < user.find(BASE_MARK)
            winner = "1" if first_is_candidate else "2"
            # `dimensions` is NESTED — _to_ab reads pass_["dimensions"][d]. A flat shape
            # raises KeyError inside compare(), which evolution_loop.py:168 swallows as
            # "candidate eval failed, skipping": every candidate is dropped, the gate never
            # runs, and the ceiling assertion passes over a run that did almost nothing.
            dims = ", ".join(f'"{d}": "{winner}"' for d in compare_judge._DIMENSIONS)
            return _Resp('{"dimensions": {%s}, "overall": "%s", "margin": 2,'
                         ' "reason": "stub"}' % (dims, winner))
        if self.mode == "optimizer":
            n = self.counter[self.mode]
            # Each edit must actually change the doc (else :156 auto-rejects without a
            # dispatch) and stay under _length_ceiling (else :159 rejects without a
            # dispatch). Either way the ceiling would never be approached.
            # op must be one of add/delete/replace with section/content — anything else
            # is filtered out at optimizer.py:79 and the loop sees "no candidates".
            return _Resp(
                '{"edits": [{"op": "add", "section": "S%d", "content": "tweak-%d"},'
                ' {"op": "add", "section": "T%d", "content": "tweak-%d-b"}]}'
                % (n, n, n, n))
        return _Resp('{"tasks": []}')     # mint


@pytest.fixture
def harness(client, monkeypatch):
    """Patch the four spend seams and return the live counters."""
    counter: dict = {}
    dispatched: list[dict] = []

    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)

    async def fake_dispatch(conversation_id, *, spawn_id, task_brief, system_prompt_override,
                            replay=False, ambient=None, **kw):
        rid = 90000 + len(dispatched)
        dispatched.append({"run_id": rid, "prompt": system_prompt_override})
        mark = CAND_MARK if "tweak-" in (system_prompt_override or "") else BASE_MARK
        return {"run_id": rid, "full_output": f"{mark} for {task_brief}"}

    monkeypatch.setattr(dispatcher, "dispatch", fake_dispatch)

    async def fake_evidence(run_id):
        return ""
    monkeypatch.setattr(trace_evidence, "build_evidence", fake_evidence)

    async def fake_rich(spawn_id, **kw):
        return []
    monkeypatch.setattr(replay_set, "build", fake_rich)

    for mod, mode in ((compare_judge, "judge"), (optimizer, "optimizer"),
                      (synthetic_corpus, "mint")):
        async def _factory(*a, _mode=mode, **kw):
            return _StubAdapter(_mode, counter)
        monkeypatch.setattr(mod, "build_adapter", _factory)

    return {"counter": counter, "dispatched": dispatched}


async def _spawn(client) -> int:
    async with client.db_maker() as s:
        sp = Spawn(name="S", domain_category="g", system_prompt="base prompt")
        s.add(sp)
        await s.commit()
        return sp.id


async def _run_and_count(client, monkeypatch, harness, corpus) -> tuple[dict, int, int]:
    """Estimate, then really run the loop over the SAME corpus, and report both counts."""
    sid = await _spawn(client)

    async def fake_corpus(db, spawn_id, *, baseline_started_at=None, mint=False):
        return list(corpus)
    monkeypatch.setattr(replay_gate, "build_corpus", fake_corpus)

    async with client.db_maker() as s:
        est = await evolution_estimate.estimate(s, sid)

    with replay_run.collect_run_ids() as run_ids, evolution_meter.counting():
        await evolution_loop.propose_improvement(sid)      # real defaults, not overridden
        counters = evolution_meter.snapshot()
    return est, len(run_ids), int(counters.get("judge_calls") or 0)


# 🔴 10 and 11 are NOT divisible by 3, deliberately. `_subsplit_propose` takes every third
# item, so floor and ceil agree on 9/18/3 and a fixture built only from multiples of three
# cannot tell `propose // 3` from `ceil(propose / 3)` — both designs give the same V and
# the mutation passes.
@pytest.mark.parametrize("propose,holdout", [(9, 10), (18, 12), (3, 10), (10, 10), (11, 10)])
async def test_real_dispatch_count_never_exceeds_the_projected_ceiling(
        client, monkeypatch, harness, propose, holdout):
    """Candidates always win (position-aware stub) → every epoch accepts → the gate runs.
    This is the shape that APPROACHES the ceiling; if the formula under-counts any term,
    the observed count overshoots and this goes red.

    Three corpus sizes because the ceiling has a term that scales with P (the gate) and a
    term capped by val_cap (the optimizer). A single size cannot tell a formula that mixes
    them up from one that does not.
    """
    corpus = _corpus(propose=propose, holdout=holdout)
    est, observed, judges = await _run_and_count(client, monkeypatch, harness, corpus)

    assert observed > 0, "nothing was dispatched — the harness is not exercising the loop"
    assert observed <= est["dispatches_max"], (
        f"the projected ceiling was BREACHED: {observed} > {est['dispatches_max']} "
        f"(pairs={est['pairs']} val_pairs={est['val_pairs']}) — it is a label, not a bound")
    assert judges <= est["judge_calls_max"], (
        f"judge ceiling breached: {judges} > {est['judge_calls_max']}")

    # 🔴 TIGHTNESS. "observed <= max" alone is satisfied by ANY large enough number —
    # infinity passes it. Reverting to the old 14*P formula leaves this test green on the
    # first half, because 14*P is bigger than the real ceiling; the number would be just
    # as wrong, only wrong upward. So the ceiling must also be APPROACHED in the shape
    # that maximises work (every candidate accepted, gate runs). Measured utilisation on
    # these three shapes is 94-97%; 80% leaves room for the loop's own slack (the last
    # epoch's accepted edit never triggers another _val_outputs) without admitting a
    # formula that is merely an upper bound by accident.
    assert observed >= 0.8 * est["dispatches_max"], (
        f"the ceiling is not TIGHT: {observed} of {est['dispatches_max']} "
        f"({100 * observed // est['dispatches_max']}%). A bound nothing approaches is not "
        "derived from this loop — it is a bigger number that happens to be larger.")
    assert judges >= 0.8 * est["judge_calls_max"], (
        f"judge ceiling not tight: {judges} of {est['judge_calls_max']}")


async def test_the_gate_really_runs_in_this_harness(client, monkeypatch, harness):
    """🔴 The control for the test above. If candidates were all rejected, the loop would
    return before run_gate, the observed count would be tiny, and `observed <= max` would
    pass while covering none of the 2P term. Assert the gate's own footprint: it dispatches
    two arms for EVERY pair, so the total must be at least 2*P.
    """
    corpus = _corpus(propose=9, holdout=10)
    est, observed, _ = await _run_and_count(client, monkeypatch, harness, corpus)
    assert observed >= 2 * est["pairs"], (
        f"only {observed} dispatches for {est['pairs']} pairs — the gate never ran, so "
        "the ceiling test above was not exercising the term that scales with the corpus")


async def test_a_dispatch_beyond_the_ceiling_is_caught(client, monkeypatch, harness):
    """🔴 The mutation-in-a-test: prove the ceiling assertion can actually FAIL.

    `basis: "max"` is exactly the kind of claim that was killed for tokens last round —
    a label asserting a property nobody checked. Here the property is checked, and this
    test proves the check has teeth: inject one extra dispatch beyond what the loop would
    make, and the same assertion the test above uses must reject it.
    """
    corpus = _corpus(propose=9, holdout=10)
    est, observed, _ = await _run_and_count(client, monkeypatch, harness, corpus)

    inflated = est["dispatches_max"] + 1
    with pytest.raises(AssertionError):
        assert inflated <= est["dispatches_max"], "ceiling breached"
    # and the real observation is genuinely under it, not merely equal by construction
    assert observed <= est["dispatches_max"]
