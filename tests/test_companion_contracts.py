from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from arslan.companion.contracts import (
    AcceptanceCheck, ActionJournal, BudgetSpec, CheckResult, ConnectionMetadata,
    ContextReceipt, Grant, ResourceRef, Scope, TaskSpec, TaskState, ToolResult, WorkerBrief,
)

NOW = datetime(2026, 9, 14, tzinfo=UTC)
SCOPE = Scope(kind="task", owner_id="owner", task_id="task")
EVIDENCE = ResourceRef(id="artifact", kind="artifact", revision=1)


def task():
    return TaskSpec(id="task", scope=SCOPE, instruction="Read the fixture", locale="en",
                    acceptance=(AcceptanceCheck(id="output", description="Expected output",
                                                evaluator="deterministic"),))


@pytest.mark.parametrize("contract", [
    AcceptanceCheck, ActionJournal, BudgetSpec, CheckResult, ConnectionMetadata,
    ContextReceipt, Grant, ResourceRef, Scope, TaskSpec, TaskState, ToolResult, WorkerBrief,
])
def test_every_contract_has_closed_versioned_schema(contract):
    schema = contract.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == 1


@pytest.mark.parametrize("entry", ["host", "worker", "recipe"])
def test_shared_acceptance_semantics_for_synthetic_entries(entry):
    spec = task()
    state = TaskState(task_id=spec.id, spec_revision=1, run_id=entry, sequence=1,
                      phase="succeeded", updated_at=NOW)
    with pytest.raises(ValueError, match="all acceptance"):
        state.validated_for(spec)
    passed = CheckResult(check_id="output", status="passed", evaluator="deterministic",
                         evidence=(EVIDENCE,))
    assert state.model_copy(update={"results": (passed,)}).validated_for(spec)
    failed = passed.model_copy(update={"status": "failed"})
    with pytest.raises(ValueError, match="all acceptance"):
        state.model_copy(update={"results": (failed,)}).validated_for(spec)


def test_native_budget_adapter_does_not_rename_or_drop_limits():
    spec = BudgetSpec(model_requests=2, tokens=400, tool_calls=3)
    limits = spec.to_native()
    assert limits.model_requests == 2 and limits.tokens == 400 and limits.tool_calls == 3
    assert limits.artifact_bytes == spec.artifact_bytes


def test_context_request_evidence_is_nonnegative_and_cannot_invent_responses():
    base = dict(id="receipt", task_id="task", run_id="run", memory_mode="normal")
    for fields in ({"request_attempts": True}, {"provider_responses": -1}, {"provider_responses": 1}):
        with pytest.raises(ValidationError):
            ContextReceipt(**base, **fields)
    assert ContextReceipt(**base, request_attempts=2, provider_responses=1).request_attempts == 2


@pytest.mark.parametrize("field,value", [
    ("model_requests", True), ("tokens", 0), ("wall_seconds", float("nan")),
    ("wall_seconds", float("inf")), ("artifact_bytes", -1),
])
def test_budget_rejects_invalid_limits(field, value):
    with pytest.raises(ValidationError):
        BudgetSpec(**{field: value})


def test_scope_rejects_cross_kind_ids():
    with pytest.raises(ValidationError):
        Scope(kind="personal", owner_id="owner", project_id="project")
    with pytest.raises(ValidationError):
        TaskSpec(id="other", scope=SCOPE, instruction="x", locale="en", acceptance=task().acceptance)


def test_secret_values_are_not_connection_metadata():
    with pytest.raises(ValidationError):
        ConnectionMetadata(id="c", owner_id="o", provider="mail", credential_ref="opaque",
                           status="connected", password="must-not-serialize")


def test_denial_cannot_claim_effects_and_writes_need_journal():
    base = dict(call_id="c", task_id="task", run_id="run")
    with pytest.raises(ValidationError):
        ToolResult(**base, status="denied", effects=("read",), error_code="policy_denied")
    with pytest.raises(ValidationError):
        ToolResult(**base, status="succeeded", effects=("external_write",))
    assert ToolResult(**base, status="uncertain", effects=("external_write",),
                      journal_id="j", error_code="response_lost")


@pytest.mark.parametrize("mode", ["temporary", "disabled"])
def test_receipts_exclude_memory_in_private_modes(mode):
    with pytest.raises(ValidationError):
        ContextReceipt(id="receipt", task_id="task", run_id="run", memory_mode=mode,
                       used=(ResourceRef(id="memory", kind="memory", revision=1),))


def test_grant_expiry_and_revocation_are_fail_closed():
    grant = Grant(id="grant", connection_id="c", scope=SCOPE, actions=("draft.create",),
                  resource_ids=("mailbox",), issued_at=NOW, expires_at=NOW + timedelta(hours=1),
                  confirmation_ref="approval")
    assert grant.is_current(NOW)
    assert not grant.is_current(NOW + timedelta(hours=1))
    assert not grant.model_copy(update={"revoked_at": NOW}).is_current(NOW)
    with pytest.raises(ValueError):
        grant.is_current(NOW.replace(tzinfo=None))


def test_confirmed_action_requires_executor_evidence():
    with pytest.raises(ValidationError):
        ActionJournal(id="j", task_id="task", run_id="run", call_id="call",
                      grant_id="grant", idempotency_key="key", action="draft.create",
                      target_id="mailbox", status="confirmed", updated_at=NOW)


def test_critical_checks_cannot_be_model_only():
    with pytest.raises(ValidationError):
        AcceptanceCheck(id="auth", description="Authorized action", evaluator="model", critical=True)


def test_roundtrip_preserves_task_spec():
    spec = task()
    assert TaskSpec.model_validate_json(spec.model_dump_json()) == spec
