
import anyio

from server.orchestrator import dispatcher
from server.services import compare_judge, evaluator


def _items(n):
    return [{"run_id": i, "task": f"t{i}", "baseline_output": f"base{i}",
             "baseline_overall": 6.0, "baseline_dims": {}} for i in range(n)]


def _stub_gen(monkeypatch):
    async def fake_dispatch(conversation_id, *, spawn_id, task_brief, system_prompt_override=None,
                            persist=True, **kw):
        return {"full_output": "cand", "spawn_name": "S",
                "summary_message_id": None, "assistant_message_id": None, "escalation": None}
    monkeypatch.setattr(dispatcher, "dispatch", fake_dispatch)


def _stub_compare(monkeypatch, verdicts):
    seq = iter(verdicts)
    async def fake_compare(*, task, persona, output_a, output_b, item=None):
        return next(seq)
    monkeypatch.setattr(compare_judge, "compare", fake_compare)


def _v(overall, fab="tie", ident="tie", comp="tie"):
    return {"dimensions": {"fabrication": fab, "identity": ident, "completion": comp},
            "overall": overall, "margin": 1.0, "position_sensitive": False, "reason": "r"}


async def test_gate_pass_when_better_and_no_regression(monkeypatch):
    _stub_gen(monkeypatch)
    _stub_compare(monkeypatch, [_v("b", fab="b"), _v("b", comp="b")])
    out = await evaluator.evaluate(spawn_id=1, persona="p", candidate_prompt="C", replay_items=_items(2))
    assert out["aggregate"]["overall"] == {"better": 2, "worse": 0, "tie": 0}
    assert out["gate"]["passed"] is True


async def test_gate_fail_when_dim_regresses(monkeypatch):
    _stub_gen(monkeypatch)
    _stub_compare(monkeypatch, [_v("b", ident="a"), _v("b", ident="a")])
    out = await evaluator.evaluate(spawn_id=1, persona="p", candidate_prompt="C", replay_items=_items(2))
    assert out["gate"]["passed"] is False


async def test_gate_fail_when_not_better(monkeypatch):
    _stub_gen(monkeypatch)
    _stub_compare(monkeypatch, [_v("tie"), _v("a")])
    out = await evaluator.evaluate(spawn_id=1, persona="p", candidate_prompt="C", replay_items=_items(2))
    assert out["gate"]["passed"] is False


async def test_empty_replay_fails_gate(monkeypatch):
    _stub_gen(monkeypatch)
    _stub_compare(monkeypatch, [])
    out = await evaluator.evaluate(spawn_id=1, persona="p", candidate_prompt="C", replay_items=[])
    assert out["gate"]["passed"] is False


def test_evaluate_uses_custom_scorer_and_dims(monkeypatch):
    async def fake_dispatch(conv, *, spawn_id, task_brief, system_prompt_override, persist):
        return {"full_output": "candidate-out"}
    monkeypatch.setattr(evaluator.dispatcher, "dispatch", fake_dispatch)

    async def fake_scorer(*, task, persona, output_a, output_b, item):
        return {"dimensions": {"benchmark": "b"}, "overall": "b", "margin": 1.0}
    fake_scorer.dimensions = ("benchmark",)

    items = [{"run_id": 1, "task": "t", "baseline_output": "base"}]
    res = anyio.run(lambda: evaluator.evaluate(
        spawn_id=1, persona="p", candidate_prompt="## Role\nX", replay_items=items,
        scorer=fake_scorer))
    assert res["gate"]["passed"] is True
    assert "benchmark" in res["aggregate"]["dims"]


def test_evaluate_uses_running_best_baseline(monkeypatch):
    captured = {}

    async def fake_dispatch(conv, *, spawn_id, task_brief, system_prompt_override, persist):
        return {"full_output": "candidate-out"}
    monkeypatch.setattr(evaluator.dispatcher, "dispatch", fake_dispatch)

    async def fake_scorer(*, task, persona, output_a, output_b, item):
        captured["a"] = output_a
        return {"dimensions": {"completion": "tie"}, "overall": "tie", "margin": 0.0}
    fake_scorer.dimensions = ("completion",)

    items = [{"run_id": 1, "task": "t", "baseline_output": "STORED"}]
    anyio.run(lambda: evaluator.evaluate(
        spawn_id=1, persona="p", candidate_prompt="## Role\nX", replay_items=items,
        scorer=fake_scorer, baseline_outputs={1: "RUNNING_BEST"}))
    assert captured["a"] == "RUNNING_BEST"  # compared vs running-best, not the stored baseline
