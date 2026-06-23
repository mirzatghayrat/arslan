"""Evaluator: run a candidate prompt over a replay set, compare each output to its
baseline via compare_judge, aggregate, and apply the '性能不减' gate.

Gate PASS iff: overall.better > overall.worse AND overall.better >= 1
AND no dimension regresses (dims[d].worse <= dims[d].better for every dim).
Default FAIL (no evidence / not clearly better / any regression).
"""
from __future__ import annotations

from server.orchestrator import dispatcher
from server.services import compare_judge

_DIMENSIONS = ("fabrication", "identity", "completion")


def _gate(aggregate: dict) -> dict:
    o = aggregate["overall"]
    reasons: list[str] = []
    passed = o["better"] > o["worse"] and o["better"] >= 1
    if not passed:
        reasons.append("overall not better than baseline")
    for d in _DIMENSIONS:
        c = aggregate["dims"][d]
        if c["worse"] > c["better"]:
            passed = False
            reasons.append(f"{d} regressed")
    return {"passed": passed, "reason": "; ".join(reasons) or "improves without regression",
            "aggregate": aggregate}


async def evaluate(*, spawn_id: int, persona: str, candidate_prompt: str,
                   replay_items: list[dict]) -> dict:
    overall = {"better": 0, "worse": 0, "tie": 0}
    dims = {d: {"better": 0, "worse": 0, "tie": 0} for d in _DIMENSIONS}
    items: list[dict] = []

    def _bump(bucket: dict, value: str) -> None:
        if value == "b":
            bucket["better"] += 1
        elif value == "a":
            bucket["worse"] += 1
        else:
            bucket["tie"] += 1

    for it in replay_items:
        gen = await dispatcher.dispatch(
            "evolution-eval", spawn_id=spawn_id, task_brief=it["task"],
            system_prompt_override=candidate_prompt, persist=False,
        )
        candidate_output = gen.get("full_output", "")
        v = await compare_judge.compare(
            task=it["task"], persona=persona,
            output_a=it["baseline_output"], output_b=candidate_output,
        )
        _bump(overall, v.get("overall", "tie"))
        for d in _DIMENSIONS:
            _bump(dims[d], (v.get("dimensions") or {}).get(d, "tie"))
        items.append({"run_id": it.get("run_id"), "task": it["task"], "verdict": v})

    aggregate = {"overall": overall, "dims": dims}
    return {"items": items, "aggregate": aggregate, "gate": _gate(aggregate)}
