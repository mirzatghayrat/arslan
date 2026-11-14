"""L7 goal mode's types (docs/plans/0164/L7-goal-mode.md). L7-1 only declares them: nothing reads them yet.

A goal is a background task whose acceptance checks are the goal, run by today's `_run_native`. Its spec (`GoalSpec`)
rides on `TurnRequest.goal`; what its rounds have recorded (`GoalProgress`) rides on `Progress.goal`, written in the
same checkpoint as each verdict. Both are frozen: state is recorded when it happens and never worked out again from
the transcript. A new value replaces the old one whole (`model_copy(update=...)`).
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from arslan.companion.contracts import Contract, Identifier, NonnegativeInt
from arslan.execution_budget import DEFAULT_TIER, MAX_USD_CAP

OBJECTIVE_MAX = 4000
CRITERIA_MAX = 5                 # as background_jobs.MAX_CRITERIA; the user's `check:` lines come on top
COMMAND_CHECKS_MAX = 5
BLOCKED_AFTER = 3                # rounds in a row without progress (Codex's audit)
PROTECTED_FILES_MAX = 2000
PROTECTED_BYTES_MAX = 50 * 1024 * 1024

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
RelPath = Annotated[str, Field(min_length=1, max_length=1024)]

GoalStatus = Literal["not_started", "active", "paused", "blocked", "budget_limited", "interrupted", "review",
                     "complete", "cleared"]
# Each status on the existing task row: (phase, pause reason). No new phase, table or migration.
STATUS_PHASE: dict[str, tuple[str, str | None]] = {
    "not_started": ("waiting_user", "goal_not_started"),
    "active": ("running", None),
    "paused": ("waiting_user", "goal_paused"),
    "blocked": ("waiting_user", "goal_blocked"),
    "budget_limited": ("waiting_user", "task_budget_exhausted"),
    "interrupted": ("waiting_user", "process_interrupted"),
    "review": ("waiting_user", "acceptance_review_required"),   # the user's own checks, or a protected file changed
    "complete": ("succeeded", None),
    "cleared": ("cancelled", None),
}


class GoalCheck(Contract):
    """One check of a goal. Met only through its own condition, never by the reply or a receipt naming its path.
    `by_user`: the user wrote it or confirmed it on the form (a judgement check's path counts only then).
    `user_confirmed`: "I'll confirm this myself": never judged by the model, never met by Arslan."""
    id: Identifier
    description: Annotated[str, Field(min_length=1, max_length=300)]
    kind: Literal["file_saved", "file_contains", "sources_read", "judgement", "check"]
    path: Annotated[str, Field(min_length=1, max_length=240)] | None = None
    phrases: tuple[Annotated[str, Field(min_length=1, max_length=200)], ...] = Field(default=(), max_length=32)
    minimum: Annotated[int, Field(ge=1, le=20, strict=True)] | None = None
    argv: tuple[Annotated[str, Field(max_length=2000)], ...] = Field(default=(), max_length=64)
    outputs: tuple[Annotated[str, Field(min_length=1, max_length=240)], ...] = Field(default=(), max_length=16)
    by_user: bool = False
    user_confirmed: bool = False

    @model_validator(mode="after")
    def condition_fits_kind(self):
        if self.kind in {"file_saved", "file_contains"} and self.path is None:
            raise ValueError(f"{self.kind} names a file")
        if (self.kind == "file_contains") != bool(self.phrases):
            raise ValueError("phrases belong to file_contains, which needs at least one")
        if (self.kind == "check") != bool(self.argv):
            raise ValueError("argv belongs to a check command, which needs one")
        if self.kind == "check" and not self.by_user:
            raise ValueError("only the user writes check: lines; drafting never does")
        if self.outputs and self.kind != "check":
            raise ValueError("declared outputs belong to the user's check: line")
        if any(p.endswith("/") or not p.rsplit("/", 1)[-1].strip("*") for p in self.outputs):
            raise ValueError("a declared output is a name or a glob, never a whole folder")
        if self.minimum is not None and self.kind not in {"file_saved", "sources_read"}:
            raise ValueError(f"minimum is not supported by {self.kind}")
        return self


class ProtectedFile(Contract):
    """A protected file's digest at Start (or of its test section: `[tool.pytest.*]`, a `package.json` key)."""
    path: RelPath
    sha256: Sha256 | None = None     # None: the check's argv names it but it didn't exist at Start (a warning)
    section: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    size: NonnegativeInt = 0


class ProtectedSet(Contract):
    """Fixed at Start, re-recorded only by a user edit of the goal. `patterns`: where a new file stops the goal."""
    files: tuple[ProtectedFile, ...] = Field(default=(), max_length=PROTECTED_FILES_MAX)
    patterns: tuple[RelPath, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def bounded(self):
        if sum(item.size for item in self.files) > PROTECTED_BYTES_MAX:
            raise ValueError("the protected set is over 50 MB; narrow it")
        return self


class GoalSpec(Contract):
    """What the user set: the objective, its checks, the protected set (from Start), the job's tier and cap.
    The steer key is the job's id, on `TurnRequest.steer_key`, not here."""
    objective: Annotated[str, Field(min_length=1, max_length=OBJECTIVE_MAX)]
    checks: tuple[GoalCheck, ...] = Field(min_length=1, max_length=CRITERIA_MAX + COMMAND_CHECKS_MAX)
    protected: ProtectedSet | None = None
    tier: Literal["lean", "standard", "ample"] = DEFAULT_TIER
    usd_cap: Annotated[float, Field(gt=0, le=MAX_USD_CAP, allow_inf_nan=False)] | None = None   # never raised by itself

    @model_validator(mode="after")
    def bounded_checks(self):
        ids = [check.id for check in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate goal check")
        if sum(check.kind != "check" for check in self.checks) > CRITERIA_MAX:
            raise ValueError(f"at most {CRITERIA_MAX} criteria")
        if sum(check.kind == "check" for check in self.checks) > COMMAND_CHECKS_MAX:
            raise ValueError(f"at most {COMMAND_CHECKS_MAX} check: lines")
        return self


class SeenMeasure(Contract):
    """One (check, measure) value this goal produced: a digest of the check's own measure (a `check:` run's exit
    code and output, the phrases found, the files or sources counted), and its size for the counts and sets."""
    check_id: Identifier
    digest: Sha256
    size: NonnegativeInt | None = None


class GoalProgress(Contract):
    """The rounds' record, on `Progress.goal`. Resume keeps it (the seen set included) and resets the streak; an edit
    (a spec revision) starts a fresh one."""
    status: GoalStatus = "not_started"
    round: Annotated[int, Field(ge=0, le=10_000, strict=True)] = 0
    stall: Annotated[int, Field(ge=0, le=BLOCKED_AFTER, strict=True)] = 0   # rounds in a row without progress
    unmet: tuple[Identifier, ...] = Field(default=(), max_length=CRITERIA_MAX + COMMAND_CHECKS_MAX)
    ever_met: tuple[Identifier, ...] = Field(default=(), max_length=CRITERIA_MAX + COMMAND_CHECKS_MAX)
    seen: tuple[SeenMeasure, ...] = Field(default=(), max_length=1000)
    accepted: tuple[ProtectedFile, ...] = Field(default=(), max_length=PROTECTED_FILES_MAX)   # declared outputs
    last_receipt: NonnegativeInt = 0   # the trace index the last verdict read up to
