"""Scorer/fixture tests, explicitly not evidence that an agent passed 30 tasks."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.companion.report import load_catalog
from evals.companion.schema import Attempt, Budget, Catalog, CheckEvidence, Criterion
from evals.companion.scoring import judge_attempt, summarize


def _attempt(case, index=1, **changes):
    value = {
        "task_id": case.id, "task_revision": case.revision, "attempt": index,
        "environment": "synthetic", "initial_state_sha256": "a" * 64,
        "configuration_sha256": "b" * 64, "status": "succeeded",
        "used": {"model_calls": 1, "tool_calls": 0, "tokens": 100, "wall_seconds": 1},
        "checks": [{"criterion_id": c.id, "status": "passed", "evaluator": c.evaluator,
                    "evidence_refs": [f"synthetic://checker/{case.id}/{c.id}"]}
                   for c in case.criteria],
    }
    value.update(changes)
    return Attempt.model_validate(value)


def test_catalog_is_thirty_task_families_not_unit_test_selectors():
    catalog = load_catalog()
    assert len(catalog.cases) == 30
    assert Counter(c.domain for c in catalog.cases) == {
        "research": 8, "apple": 10, "design": 8, "continuity": 4,
    }
    assert all(c.negative_example and c.prompt for c in catalog.cases)
    assert all(c.input_state == "real_inputs_pending" for c in catalog.cases)
    assert not any("tests/" in c.initial_state_ref for c in catalog.cases)


def test_sixty_multiturn_memory_specs_are_not_marked_passed():
    path = Path(__file__).parents[1] / "evals/companion/memory-scenarios.json"
    data = json.loads(path.read_text())
    scenarios = data["scenarios"]
    assert len(scenarios) == len({s["id"] for s in scenarios}) == 60
    assert Counter(s["group"] for s in scenarios) == {
        "M01": 8, "M02": 8, "M03": 8, "M04": 8,
        "M05": 7, "M06": 7, "M07": 7, "M08": 7,
    }
    assert all(len(s["turns"]) >= 2 and s["initial_state"] and s["assertions"] for s in scenarios)
    assert all(s["fixture_status"] == "specification_pending_runtime_binding" for s in scenarios)
    assert all(s["data_classification"] == "synthetic_only" for s in scenarios)


@pytest.mark.parametrize("case", load_catalog().cases, ids=lambda case: case.id)
def test_every_task_accepts_positive_and_rejects_negative_checker_evidence(case):
    positive = _attempt(case)
    assert judge_attempt(case, positive)["passed"]
    checks = [check.model_dump() for check in positive.checks]
    checks[0]["status"] = "failed"
    negative = _attempt(case, checks=checks)
    assert not judge_attempt(case, negative)["passed"]


def test_unrun_and_synthetic_results_cannot_claim_a_live_score():
    catalog = load_catalog()
    empty = summarize(catalog, [])
    assert (empty["passed"], empty["denominator"], empty["missing"]) == (0, 90, 90)
    synthetic = summarize(catalog, [_attempt(c, i) for c in catalog.cases for i in (1, 2, 3)])
    assert synthetic["passed"] == 90
    assert synthetic["live_completion_rate"] is None
    assert synthetic["live_score_eligible"] is False
    assert synthetic["release_blocked"] is True


def test_three_attempts_use_all_results_not_best_of_three():
    catalog = load_catalog()
    case = catalog.cases[0]
    report = summarize(catalog, [_attempt(case), _attempt(case, 2, status="failed")])
    assert (report["passed"], report["denominator"], report["missing"]) == (1, 90, 88)
    assert report["per_task"][case.id] == 1
    assert report["latency_seconds"] == {"p50": 1, "p95": 1}


@pytest.mark.parametrize("change", [
    {"status": "partial"}, {"status": "unsupported"}, {"human_corrections": 1},
    {"checks": []}, {"task_revision": 2}, {"tool_side_effects": ["release_app"]},
    {"used": {"model_calls": 33, "tool_calls": 0, "tokens": 100, "wall_seconds": 1}},
])
def test_false_success_is_rejected(change):
    case = load_catalog().cases[0]
    assert not judge_attempt(case, _attempt(case, **change))["passed"]


def test_duplicate_unknown_and_changed_configuration_are_not_silently_dropped():
    catalog = load_catalog()
    case = catalog.cases[0]
    with pytest.raises(ValueError, match="duplicate attempt"):
        summarize(catalog, [_attempt(case), _attempt(case)])
    with pytest.raises(ValueError, match="unknown task"):
        summarize(catalog, [_attempt(case, task_id="unknown")])
    report = summarize(catalog, [_attempt(case), _attempt(case, 2, configuration_sha256="c" * 64)])
    assert report["passed"] == 0


def test_live_failure_is_not_hidden_by_an_aggregate_pass_rate():
    source = load_catalog()
    cases = [case.model_copy(update={"input_state": "real_frozen",
             "initial_state_sha256": "a" * 64, "authorization_ref": "approval-1"})
             for case in source.cases]
    catalog = Catalog.model_validate({**source.model_dump(), "cases": cases})
    attempts = [_attempt(case, i, environment="live", authorization_ref="approval-1")
                for case in cases for i in (1, 2, 3)]
    first = attempts[0].model_dump()
    first["checks"][1]["status"] = "failed"
    attempts[0] = Attempt.model_validate(first)
    result = summarize(catalog, attempts)
    assert result["live_score_eligible"]
    assert result["live_completion_rate"] == 89 / 90
    assert result["critical_failures"] and result["release_blocked"]


def test_a_missing_critical_check_is_a_release_blocker():
    case = load_catalog().cases[0]
    evidence = _attempt(case).model_dump()
    evidence["checks"][1]["status"] = "not_run"
    result = judge_attempt(case, Attempt.model_validate(evidence))
    assert "authorization" in result["critical_unverified"]
    assert not result["passed"]


def test_schema_rejects_optional_safety_unsupported_verdicts_and_invalid_budgets():
    with pytest.raises(ValidationError):
        Criterion(id="auth", description="authorization", evaluator="model", critical=True)
    with pytest.raises(ValidationError):
        CheckEvidence(criterion_id="auth", status="passed", evaluator="deterministic")
    with pytest.raises(ValidationError):
        Budget(model_calls=True, tool_calls=0, tokens=0, wall_seconds=0)
    with pytest.raises(ValidationError):
        Budget(model_calls=0, tool_calls=0, tokens=0, wall_seconds=float("nan"))
    with pytest.raises(ValidationError):
        _attempt(load_catalog().cases[0], environment="live")
