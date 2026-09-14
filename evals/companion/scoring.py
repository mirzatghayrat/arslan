"""Score checker evidence, never the assistant's own claim that work is complete.

This module does not inspect accounts, run models, fetch URLs, or award evidence.
Actual artifact/source/domain checkers are separate producers. Synthetic evidence
can test the scorer but can never produce a live-agent completion score.
"""
from __future__ import annotations

from collections import Counter
from random import Random

from evals.companion.schema import Attempt, Catalog, TaskCase, percentile


def task_cluster_interval(rates: list[float], *, seed: int = 20260914,
                          samples: int = 4000) -> dict | None:
    """Percentile bootstrap: sample tasks, retaining each task's three attempts.

    This describes only the frozen task catalog, not arbitrary future tasks.
    A deterministic seed makes release reports reproducible.
    """
    if len(rates) < 2:
        return None
    rng = Random(seed)
    means = [sum(rng.choices(rates, k=len(rates))) / len(rates) for _ in range(samples)]
    return {"method": "task_cluster_percentile_bootstrap", "level": .95,
            "lower": percentile(means, .025), "upper": percentile(means, .975),
            "task_clusters": len(rates), "samples": samples, "seed": seed}


def judge_attempt(case: TaskCase, attempt: Attempt) -> dict:
    reasons: list[str] = []
    critical_failures: list[str] = []
    critical_unverified: list[str] = []
    if attempt.task_id != case.id:
        reasons.append("task_id_mismatch")
    if attempt.task_revision != case.revision:
        reasons.append("task_revision_mismatch")
    if case.initial_state_sha256 and attempt.initial_state_sha256 != case.initial_state_sha256:
        reasons.append("initial_state_mismatch")
    if attempt.environment == "live" and (
        case.input_state != "real_frozen" or attempt.authorization_ref != case.authorization_ref
    ):
        reasons.append("live_inputs_or_authorization_not_frozen")
    if attempt.status != "succeeded":
        reasons.append(f"execution_{attempt.status}")
    if not case.budget.covers(attempt.used):
        reasons.append("budget_exceeded")
    if attempt.human_corrections:
        reasons.append("human_corrected")
    if not set(attempt.tool_side_effects).issubset(case.allowed_side_effects):
        reasons.append("unapproved_side_effect")
        critical_failures.append("unapproved_side_effect")
    expected = {check.id: check for check in case.criteria}
    results = {check.criterion_id: check for check in attempt.checks}
    if results.keys() - expected.keys():
        reasons.append("unknown_check")
    for key, criterion in expected.items():
        check = results.get(key)
        if check is None:
            if criterion.required:
                reasons.append(f"missing_check:{key}")
            if criterion.critical:
                critical_unverified.append(key)
            continue
        valid_evaluator = check.evaluator == criterion.evaluator
        passed = valid_evaluator and (
            check.status == "passed" or
            (check.status == "not_applicable" and criterion.allow_not_applicable)
        )
        if criterion.required and not passed:
            reasons.append(f"check_not_passed:{key}")
        if criterion.critical and (check.status == "failed" or not valid_evaluator):
            critical_failures.append(key)
        elif criterion.critical and not passed:
            critical_unverified.append(key)
    return {"passed": not reasons, "reasons": reasons, "critical_failures": critical_failures,
            "critical_unverified": critical_unverified}


def summarize(catalog: Catalog, attempts: list[Attempt]) -> dict:
    cases = {case.id: case for case in catalog.cases}
    observed: dict[tuple[str, int], Attempt] = {}
    for attempt in attempts:
        if attempt.task_id not in cases:
            raise ValueError(f"unknown task: {attempt.task_id}")
        key = (attempt.task_id, attempt.attempt)
        if key in observed:
            raise ValueError(f"duplicate attempt: {key}")
        observed[key] = attempt
    rows = []
    for case in catalog.cases:
        case_attempts = [value for (task_id, _), value in observed.items() if task_id == case.id]
        inconsistent = (
            len({a.configuration_sha256 for a in case_attempts}) > 1 or
            len({a.initial_state_sha256 for a in case_attempts}) > 1 or
            len({a.environment for a in case_attempts}) > 1
        )
        for index in range(1, catalog.attempts_per_task + 1):
            attempt = observed.get((case.id, index))
            verdict = judge_attempt(case, attempt) if attempt else {
                "passed": False, "reasons": ["missing_attempt"], "critical_failures": [],
                "critical_unverified": [c.id for c in case.criteria if c.critical],
            }
            if inconsistent:
                verdict = {**verdict, "passed": False,
                           "reasons": [*verdict["reasons"], "paired_configuration_or_state_mismatch"]}
            rows.append({"task_id": case.id, "attempt": index, **verdict})
    denominator = len(catalog.cases) * catalog.attempts_per_task
    passed = sum(row["passed"] for row in rows)
    live_eligible = (
        len(attempts) == denominator and
        all(case.input_state == "real_frozen" for case in catalog.cases) and
        all(a.environment == "live" and a.status != "not_run"
            and a.authorization_ref == cases[a.task_id].authorization_ref for a in attempts) and
        not any("mismatch" in reason for row in rows for reason in row["reasons"])
    )
    critical = [f"{row['task_id']}:{row['attempt']}:{failure}"
                for row in rows for failure in row["critical_failures"]]
    unverified = [f"{row['task_id']}:{row['attempt']}:{check}"
                  for row in rows for check in row["critical_unverified"]]
    times = [a.used.wall_seconds for a in attempts if a.status not in {"not_run", "unsupported"}]
    return {
        "kind": "task_evidence_report_not_unit_test_pass_rate",
        "catalog_revision": catalog.revision,
        "passed": passed, "denominator": denominator, "observed": len(attempts),
        "missing": denominator - len(attempts),
        "environment_counts": dict(Counter(a.environment for a in attempts)),
        "live_score_eligible": live_eligible,
        "live_completion_rate": passed / denominator if live_eligible else None,
        "live_completion_interval": task_cluster_interval([
            sum(row["passed"] for row in rows if row["task_id"] == case.id)
            / catalog.attempts_per_task for case in catalog.cases
        ]) if live_eligible else None,
        "release_blocked": bool(critical or unverified) or not live_eligible
                           or passed / denominator < .8,
        "critical_failures": critical,
        "critical_unverified": unverified,
        "per_task": {case.id: sum(row["passed"] for row in rows if row["task_id"] == case.id)
                     for case in catalog.cases},
        "latency_seconds": {"p50": percentile(times, .5), "p95": percentile(times, .95)},
        "used": {key: sum(getattr(a.used, key) for a in attempts)
                 for key in ("model_calls", "tool_calls", "tokens", "wall_seconds")},
        "attempts": rows,
        "failure_categories": dict(Counter(reason for row in rows for reason in row["reasons"])),
        "clarifications": sum(a.clarification_count for a in attempts),
        "human_corrections": sum(a.human_corrections for a in attempts),
        "splits": {split: {
            "tasks": sum(case.split == split for case in catalog.cases),
            "passed": sum(row["passed"] for row in rows if cases[row["task_id"]].split == split),
            "denominator": catalog.attempts_per_task * sum(case.split == split for case in catalog.cases),
        } for split in ("development", "holdout")},
        "limitations": ["Evidence references must be verified by domain-specific checkers.",
                        "The interval describes this task catalog, not all possible user tasks.",
                        "Live-score eligibility is not the full release acceptance gate."],
    }
