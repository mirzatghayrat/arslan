"""Evaluator: run a candidate prompt over a replay set, compare each output to its
baseline via a scorer (default: compare_judge.compare), aggregate, and apply the
'性能不减' gate.

Gate PASS iff: overall.better > overall.worse AND overall.better >= 1
AND no dimension regresses (dims[d].worse <= dims[d].better for every dim).
Default FAIL (no evidence / not clearly better / any regression).

The `scorer` seam: any async callable with keyword args (task, persona, output_a,
output_b, item) returning {"dimensions": {dim: "a"|"b"|"tie"}, "overall": ...,
"margin": float}. Optionally set scorer.dimensions = (...) to declare which
dimensions it scores; falls back to _DEFAULT_DIMENSIONS if absent.

The `baseline_outputs` map (run_id → output) lets the caller supply a running-best
baseline per item, overriding the stored `baseline_output` for that run_id.
"""
from __future__ import annotations

from server.db import session as db_session
from server.services import compare_judge, replay_run

_DEFAULT_DIMENSIONS = ("fabrication", "identity", "completion")


def _gate(aggregate: dict, dimensions) -> dict:
    o = aggregate["overall"]
    reasons: list[str] = []
    passed = o["better"] > o["worse"] and o["better"] >= 1
    if not passed:
        reasons.append("overall not better than baseline")
    for d in dimensions:
        c = aggregate["dims"][d]
        if c["worse"] > c["better"]:
            passed = False
            reasons.append(f"{d} regressed")
    return {"passed": passed, "reason": "; ".join(reasons) or "improves without regression",
            "aggregate": aggregate}


async def evaluate(*, spawn_id: int, persona: str, candidate_prompt: str,
                   replay_items: list[dict], scorer=None,
                   baseline_outputs: dict | None = None) -> dict:
    scorer = scorer or compare_judge.compare
    dimensions = getattr(scorer, "dimensions", _DEFAULT_DIMENSIONS)
    baseline_outputs = baseline_outputs or {}

    overall = {"better": 0, "worse": 0, "tie": 0}
    dims = {d: {"better": 0, "worse": 0, "tie": 0} for d in dimensions}
    items: list[dict] = []

    def _bump(bucket: dict, value: str) -> None:
        if value == "b":
            bucket["better"] += 1
        elif value == "a":
            bucket["worse"] += 1
        else:
            bucket["tie"] += 1

    # Hermetic, byte-identical arms: one ambient snapshot for the whole eval; each candidate
    # dispatch goes through run_arm (dispatch(replay=True) + shared ambient), matching the
    # final ReplayGate. Sealed = the model sees only replay-safe tools (candidate scored on
    # the read-only subset — see plan honesty note).
    async with db_session.AsyncSessionLocal() as db:
        ambient = await replay_run.snapshot_ambient(
            db, spawn_id=spawn_id, conversation_id=replay_run.REPLAY_CONVERSATION_ID)
        for it in replay_items:
            arm = await replay_run.run_arm(
                db, spawn_id=spawn_id, task=it["task"],
                system_prompt=candidate_prompt, ambient=ambient)
            candidate_output = arm["output"]
            baseline = baseline_outputs.get(it.get("run_id"), it["baseline_output"])
            v = await scorer(task=it["task"], persona=persona,
                             output_a=baseline, output_b=candidate_output, item=it)
            _bump(overall, v.get("overall", "tie"))
            for d in dimensions:
                _bump(dims[d], (v.get("dimensions") or {}).get(d, "tie"))
            items.append({"run_id": it.get("run_id"), "task": it["task"], "verdict": v})

    aggregate = {"overall": overall, "dims": dims}
    return {"items": items, "aggregate": aggregate, "gate": _gate(aggregate, dimensions)}
