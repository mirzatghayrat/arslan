"""Versioned evaluation inputs. A catalog entry is not an executed task result."""
from __future__ import annotations

import math
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")]
NonEmpty = Annotated[str, Field(min_length=1)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Budget(Record):
    model_calls: int = Field(ge=0, strict=True)
    tool_calls: int = Field(ge=0, strict=True)
    tokens: int = Field(ge=0, strict=True)
    wall_seconds: float = Field(ge=0, allow_inf_nan=False)

    def covers(self, used: Budget) -> bool:
        return all(getattr(used, key) <= getattr(self, key) for key in type(self).model_fields)


class Criterion(Record):
    id: Identifier
    description: NonEmpty
    evaluator: Literal["deterministic", "human", "model"]
    required: bool = True
    critical: bool = False
    allow_not_applicable: bool = False

    @model_validator(mode="after")
    def critical_is_not_optional(self) -> Self:
        if self.critical and (not self.required or self.allow_not_applicable
                              or self.evaluator == "model"):
            raise ValueError("critical checks must be required, applicable, and independently checked")
        return self


class TaskCase(Record):
    id: Identifier
    revision: int = Field(ge=1, strict=True)
    domain: Literal["research", "apple", "design", "continuity"]
    split: Literal["development", "holdout"]
    title: NonEmpty
    prompt: NonEmpty
    input_state: Literal["real_inputs_pending", "synthetic", "real_frozen"]
    initial_state_ref: NonEmpty
    initial_state_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    authorization_ref: str | None = None
    allowed_clarifications: tuple[str, ...] = ()
    allowed_side_effects: tuple[str, ...] = ()
    budget: Budget
    criteria: tuple[Criterion, ...] = Field(min_length=1)
    negative_example: NonEmpty

    @model_validator(mode="after")
    def coherent_case(self) -> Self:
        ids = [check.id for check in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate criterion IDs")
        if not any(check.required for check in self.criteria):
            raise ValueError("at least one required criterion is needed")
        if self.input_state == "real_frozen" and (
            not self.initial_state_sha256 or not self.authorization_ref
        ):
            raise ValueError("real inputs need an immutable state hash and explicit authorization")
        return self


class Catalog(Record):
    schema_version: Literal[1] = 1
    kind: Literal["task_catalog_not_results"] = "task_catalog_not_results"
    revision: int = Field(ge=1, strict=True)
    attempts_per_task: Literal[3] = 3
    cases: tuple[TaskCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self) -> Self:
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate task IDs")
        return self


class CheckEvidence(Record):
    criterion_id: Identifier
    status: Literal["passed", "failed", "not_run", "not_applicable"]
    evaluator: Literal["deterministic", "human", "model"]
    evidence_refs: tuple[NonEmpty, ...] = ()
    note: str = ""

    @model_validator(mode="after")
    def supported_verdict(self) -> Self:
        if self.status in {"passed", "failed"} and not self.evidence_refs:
            raise ValueError("a verdict needs independently produced evidence references")
        return self


class Attempt(Record):
    task_id: Identifier
    task_revision: int = Field(ge=1, strict=True)
    attempt: int = Field(ge=1, le=3, strict=True)
    environment: Literal["synthetic", "replay", "live"]
    initial_state_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    configuration_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["succeeded", "partial", "blocked", "failed", "cancelled", "not_run", "unsupported"]
    used: Budget
    checks: tuple[CheckEvidence, ...] = ()
    human_corrections: int = Field(default=0, ge=0, strict=True)
    clarification_count: int = Field(default=0, ge=0, strict=True)
    tool_side_effects: tuple[str, ...] = ()
    authorization_ref: str | None = None

    @model_validator(mode="after")
    def coherent_attempt(self) -> Self:
        ids = [check.criterion_id for check in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate check results")
        if self.environment == "live" and not self.authorization_ref:
            raise ValueError("live evidence needs an authorization reference")
        return self


def percentile(values: list[float], fraction: float) -> float | None:
    """Linear percentile over observed attempts; missing runs never acquire zero latency."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)
