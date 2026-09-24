"""Data boundaries, not authority: constructing a Grant never authorizes execution.

Secret values and raw personal context are deliberately absent from receipts.
Runtime callers must resolve references and recheck grants at the action boundary.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from arslan.execution_budget import Limits

Identifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
PositiveInt = Annotated[int, Field(gt=0, strict=True)]
NonnegativeInt = Annotated[int, Field(ge=0, strict=True)]
Locale = Literal["en", "zh", "ja", "es", "de", "fr"]
Effect = Literal["read", "local_write", "external_write", "destructive"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1


class Scope(Contract):
    kind: Literal["personal", "project", "task"]
    owner_id: Identifier
    project_id: Identifier | None = None
    task_id: Identifier | None = None

    @model_validator(mode="after")
    def consistent_scope(self):
        if self.kind == "personal" and (self.project_id or self.task_id):
            raise ValueError("personal scope cannot contain project/task IDs")
        if self.kind == "project" and (not self.project_id or self.task_id):
            raise ValueError("project scope requires only a project ID")
        if self.kind == "task" and not self.task_id:
            raise ValueError("task scope requires a task ID")
        return self


class ResourceRef(Contract):
    """Opaque ownership-checked reference, never an arbitrary privileged URL."""
    id: Identifier
    kind: Literal["artifact", "document", "image", "video", "code", "webpage", "memory"]
    revision: PositiveInt
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None
    locator: Annotated[str, Field(max_length=500)] | None = None
    title: Annotated[str, Field(max_length=240)] | None = None
    logical_key: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None


class BudgetSpec(Contract):
    model_requests: PositiveInt = 32
    tool_calls: PositiveInt = 24
    tokens: PositiveInt = 128_000
    wall_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 600
    output_tokens_per_request: PositiveInt = 16384
    artifact_bytes: PositiveInt = 100 * 1024 * 1024

    def to_native(self) -> Limits:
        return Limits(**self.model_dump(exclude={"schema_version"}))


class ValidationRule(Contract):
    """Bounded declarative assertions, never code, paths or execution authority."""
    kind: Literal["text", "json", "artifact", "image_dimensions", "research_sources", "research_evidence",
                  "code_build", "code_test", "language", "layout", "remote_readback"]
    target: Annotated[str, Field(max_length=240)] | None = None
    equals: Annotated[str, Field(max_length=20_000)] | None = None
    contains: tuple[Annotated[str, Field(min_length=1, max_length=2000)], ...] = Field(default=(), max_length=32)
    minimum: Annotated[int, Field(ge=0, le=1_000_000, strict=True)] | None = None
    maximum: Annotated[int, Field(ge=0, le=1_000_000, strict=True)] | None = None
    width: Annotated[int, Field(gt=0, le=32_768, strict=True)] | None = None
    height: Annotated[int, Field(gt=0, le=32_768, strict=True)] | None = None
    locale: Locale | None = None
    argv: tuple[Annotated[str, Field(max_length=2000)], ...] | None = Field(default=None, max_length=64)
    when: Literal["always", "artifacts_present"] = "always"

    @model_validator(mode="after")
    def bounded_range(self):
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum exceeds maximum")
        if self.kind == "image_dimensions" and self.width is None and self.height is None:
            raise ValueError("image dimensions require width or height")
        fields = {
            "text": {"equals", "contains", "minimum", "maximum"},
            "json": {"equals", "contains"},
            "artifact": {"target", "minimum", "maximum"},
            "image_dimensions": {"target", "width", "height", "minimum", "maximum"},
            "research_sources": {"target", "minimum", "maximum"},
            "research_evidence": set(),
            "code_build": {"target", "argv", "equals", "contains"},
            "code_test": {"target", "argv", "equals", "contains"},
            "language": {"locale"}, "layout": {"target"}, "remote_readback": {"target", "equals", "locale"},
        }[self.kind]
        for name in ("target", "equals", "contains", "minimum", "maximum", "width", "height", "locale", "argv"):
            if name not in fields and getattr(self, name) not in (None, ()):
                raise ValueError(f"{name} is not supported by {self.kind} validation")
        return self


class AcceptanceCheck(Contract):
    id: Identifier
    description: Annotated[str, Field(min_length=1, max_length=2000)]
    evaluator: Literal["deterministic", "human", "model"]
    critical: bool = False
    rule: ValidationRule | None = None

    @model_validator(mode="after")
    def critical_is_not_model_only(self):
        if self.critical and self.evaluator == "model":
            raise ValueError("critical acceptance needs deterministic or human verification")
        if self.evaluator == "model" and self.rule is not None and self.rule.kind in {
            "artifact", "image_dimensions", "research_sources", "research_evidence", "code_build", "code_test", "remote_readback"}:
            raise ValueError("factual checks need deterministic or human verification")
        return self


class TaskSpec(Contract):
    id: Identifier
    revision: PositiveInt = 1
    scope: Scope
    instruction: Annotated[str, Field(min_length=1, max_length=100_000)]
    locale: Locale
    memory_mode: Literal["normal", "disabled", "temporary"] = "normal"
    inputs: tuple[ResourceRef, ...] = ()
    acceptance: tuple[AcceptanceCheck, ...] = Field(min_length=1, max_length=64)
    budget: BudgetSpec = Field(default_factory=BudgetSpec)

    @model_validator(mode="after")
    def consistent_task(self):
        if self.scope.task_id and self.scope.task_id != self.id:
            raise ValueError("scope task ID must match task ID")
        ids = [check.id for check in self.acceptance]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate acceptance check")
        return self


class CheckResult(Contract):
    check_id: Identifier
    # `unverified` remains readable for historical records; new checks use not_run.
    status: Literal["passed", "failed", "not_run", "not_applicable", "unverified"]
    evaluator: Literal["deterministic", "human", "model"]
    evidence: tuple[ResourceRef, ...] = ()

    @model_validator(mode="after")
    def verdict_has_evidence(self):
        if self.status in {"passed", "failed", "not_applicable"} and not self.evidence:
            raise ValueError("a verdict requires evidence references")
        return self


class TaskState(Contract):
    task_id: Identifier
    spec_revision: PositiveInt
    run_id: Identifier
    sequence: NonnegativeInt
    phase: Literal["queued", "running", "waiting_user", "verifying", "succeeded", "failed", "cancelled"]
    checkpoint_ref: Identifier | None = None
    results: tuple[CheckResult, ...] = ()
    updated_at: AwareDatetime

    def validated_for(self, spec: TaskSpec) -> TaskState:
        if self.task_id != spec.id or self.spec_revision != spec.revision:
            raise ValueError("task state does not match specification")
        expected = {check.id: check for check in spec.acceptance}
        actual = {result.check_id: result for result in self.results}
        if len(actual) != len(self.results) or not actual.keys() <= expected.keys():
            raise ValueError("duplicate or unknown acceptance result")
        for key, result in actual.items():
            if result.evaluator != expected[key].evaluator:
                raise ValueError("unexpected evaluator")
        if self.phase == "succeeded" and (
            actual.keys() != expected.keys()
            or all(check.evaluator == "model" for check in expected.values())
            or any(result.status != "passed" and not (
                result.status == "not_applicable" and not expected[key].critical and expected[key].rule is not None
                and expected[key].rule.when == "artifacts_present") for key, result in actual.items())
        ):
            raise ValueError("success requires all acceptance checks to pass")
        return self


class WorkerBrief(Contract):
    id: Identifier
    task_id: Identifier
    run_id: Identifier
    spec_revision: PositiveInt
    scope: Scope
    objective: Annotated[str, Field(min_length=1, max_length=20_000)]
    input_refs: tuple[ResourceRef, ...] = ()
    grant_ids: tuple[Identifier, ...] = ()
    shared_budget_id: Identifier
    # References the parent's budget; a worker cannot create/reset one here.


class ToolResult(Contract):
    call_id: Identifier
    task_id: Identifier
    run_id: Identifier
    status: Literal["succeeded", "failed", "denied", "cancelled", "uncertain"]
    effects: tuple[Effect, ...] = ()
    artifacts: tuple[ResourceRef, ...] = ()
    journal_id: Identifier | None = None
    error_code: Identifier | None = None

    @model_validator(mode="after")
    def effect_evidence(self):
        if any(effect != "read" for effect in self.effects) and not self.journal_id:
            raise ValueError("writes require an action journal reference")
        if self.status == "denied" and self.effects:
            raise ValueError("a denied call must not execute effects")
        if self.status in {"failed", "denied", "uncertain"} and not self.error_code:
            raise ValueError("non-success requires a structured error code")
        return self


class ContextReceipt(Contract):
    id: Identifier
    task_id: Identifier
    run_id: Identifier
    memory_mode: Literal["normal", "disabled", "temporary"]
    used: tuple[ResourceRef, ...] = ()
    filter_reasons: tuple[Literal["scope", "permission", "deleted", "inactive", "sensitive", "irrelevant", "budget"], ...] = ()
    estimated_tokens: NonnegativeInt = 0
    cloud_use: Literal["not_sent", "approved"] = "not_sent"
    local_only_used: bool = False
    request_attempts: NonnegativeInt = 0
    provider_responses: NonnegativeInt = 0

    @model_validator(mode="after")
    def no_memory_when_disabled(self):
        if self.provider_responses > self.request_attempts:
            raise ValueError("provider responses require recorded request attempts")
        if self.memory_mode in {"disabled", "temporary"} and any(ref.kind == "memory" for ref in self.used):
            raise ValueError("memory is excluded from disabled/temporary tasks")
        if self.local_only_used and (self.memory_mode != "normal" or self.cloud_use == "approved"):
            raise ValueError("local-only memory cannot be part of a cloud or disabled receipt")
        return self


class ConnectionMetadata(Contract):
    id: Identifier
    owner_id: Identifier
    provider: Identifier
    credential_ref: Identifier
    status: Literal["disconnected", "connected", "needs_attention"]
    # Only the trusted credential broker resolves credential_ref.


class Grant(Contract):
    id: Identifier
    connection_id: Identifier
    scope: Scope
    actions: tuple[Identifier, ...] = Field(min_length=1)
    resource_ids: tuple[Identifier, ...] = Field(min_length=1)
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None = None
    confirmation_ref: Identifier

    @model_validator(mode="after")
    def valid_window(self):
        if self.expires_at <= self.issued_at:
            raise ValueError("grant expiration must follow issuance")
        return self

    def is_current(self, now: datetime) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("grant check requires timezone-aware time")
        return self.revoked_at is None and self.issued_at <= now < self.expires_at


class ActionJournal(Contract):
    id: Identifier
    task_id: Identifier
    run_id: Identifier
    call_id: Identifier
    grant_id: Identifier
    idempotency_key: Identifier
    action: Identifier
    target_id: Identifier
    status: Literal["prepared", "started", "confirmed", "failed", "uncertain", "cancelled"]
    evidence: tuple[ResourceRef, ...] = ()
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def confirmed_has_evidence(self):
        if self.status == "confirmed" and not self.evidence:
            raise ValueError("confirmed actions require executor evidence")
        return self
