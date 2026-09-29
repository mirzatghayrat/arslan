"""One shared budget across routing, tools, retries and nested dispatches.

Request/tool counts and wall time are hard limits. Token usage is charged when
the provider reports it (or estimated when unavailable), so its threshold gates
the NEXT request, not an exact monetary guarantee for a request already in flight.
"""
from __future__ import annotations

import asyncio
import math
import os
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import asdict, dataclass
from functools import wraps


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class Limits:
    model_requests: int = 32
    tool_calls: int = 24
    tokens: int = 128_000
    wall_seconds: float = 600
    output_tokens_per_request: int = 8192
    artifact_bytes: int = 100 * 1024 * 1024

    def __post_init__(self):
        if any(not math.isfinite(value) or value <= 0 for value in asdict(self).values()):
            raise ValueError("execution budget limits must be positive")


def configured_limits() -> Limits:
    defaults = Limits()
    names = {"model_requests": "MODEL_REQUESTS", "tool_calls": "TOOL_CALLS",
             "tokens": "TOKENS", "wall_seconds": "WALL_SECONDS",
             "output_tokens_per_request": "OUTPUT_TOKENS", "artifact_bytes": "ARTIFACT_BYTES"}
    values = {}
    for field, suffix in names.items():
        raw = os.environ.get(f"ARSLAN_RUN_MAX_{suffix}")
        values[field] = float(raw) if field == "wall_seconds" and raw else (
            int(raw) if raw else getattr(defaults, field))
    return Limits(**values)


# 0.1.43: background jobs get their own, larger budget. A job is work the user
# handed off (research, drafting, organizing); the per-turn Limits above are sized
# for one chat answer and cut such work off halfway (seen in 0.1.42 field use).
JOB_TIERS = {
    "lean": dict(model_requests=60, tool_calls=40, tokens=300_000, wall_seconds=900),
    "standard": dict(model_requests=120, tool_calls=80, tokens=600_000, wall_seconds=1800),
    "ample": dict(model_requests=240, tool_calls=160, tokens=1_200_000, wall_seconds=3600),
}
DEFAULT_JOB_TIER = "standard"
# Completion first: the tier is a SOFT limit. Reaching it switches the job to
# wrap-up (write the deliverable from what it has); the hard limit, 1.5x, only
# stops a job that cannot stop itself.
HARD_OVER_SOFT = 1.5


def job_limits(tier: str) -> Limits:
    """Soft limits for one background job. Unknown tiers fall back to the default."""
    return Limits(**JOB_TIERS.get(tier, JOB_TIERS[DEFAULT_JOB_TIER]))


def job_budget(tier: str) -> "Budget":
    soft = job_limits(tier)
    hard = Limits(model_requests=math.ceil(soft.model_requests * HARD_OVER_SOFT),
                  tool_calls=math.ceil(soft.tool_calls * HARD_OVER_SOFT),
                  tokens=math.ceil(soft.tokens * HARD_OVER_SOFT),
                  wall_seconds=soft.wall_seconds * HARD_OVER_SOFT)
    return Budget(hard, soft=soft)


class Budget:
    def __init__(self, limits: Limits | None = None, *, soft: Limits | None = None):
        self.limits = limits or configured_limits()
        self.soft = soft
        self.id = uuid.uuid4().hex
        self.started = time.monotonic()
        self.model_requests = 0
        self.tool_calls = 0
        self.tokens = 0
        self.artifact_bytes = 0
        self.stop_reason: str | None = None

    @classmethod
    def from_snapshot(cls, snapshot: dict, *, limits: Limits | None = None) -> Budget:
        """Restore charged work, never reset it or silently widen its ceiling.

        Downtime is not execution time. The elapsed execution recorded before a
        crash remains charged; every new live interval starts at that offset.
        Token overrun is legal here because accounting is post-response.
        """
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("used"), dict):
            raise ValueError("invalid execution budget snapshot")
        saved = snapshot.get("limits")
        if not isinstance(saved, dict) or set(saved) != set(asdict(Limits())):
            raise ValueError("invalid execution budget limits")
        for key, value in saved.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("invalid execution budget limit")
            if key != "wall_seconds" and not isinstance(value, int):
                raise ValueError("budget counters require integer limits")
        ceiling = Limits(**saved)
        if limits is not None:
            ceiling = Limits(**{key: min(value, getattr(limits, key)) for key, value in saved.items()})
        soft_saved = snapshot.get("soft_limits")
        soft = None
        if soft_saved is not None:   # background jobs (0.1.43): the wrap-up point survives a restore
            if not isinstance(soft_saved, dict) or set(soft_saved) != set(asdict(Limits())):
                raise ValueError("invalid execution budget soft limits")
            soft = Limits(**soft_saved)
        budget = cls(ceiling, soft=soft)
        identity = snapshot.get("id")
        if not isinstance(identity, str) or not identity or len(identity) > 200:
            raise ValueError("invalid execution budget identity")
        budget.id = identity
        used = snapshot["used"]
        for key in ("model_requests", "tool_calls", "tokens", "artifact_bytes", "wall_seconds"):
            value = used.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("invalid execution budget usage")
            if key != "wall_seconds":
                if not isinstance(value, int):
                    raise ValueError("budget counters require integers")
                setattr(budget, key, value)
        budget.started = time.monotonic() - used["wall_seconds"]
        reason = snapshot.get("stop_reason")
        if reason is not None and reason not in {"model_requests", "tool_calls", "tokens", "artifact_bytes", "wall_seconds"}:
            raise ValueError("invalid execution budget stop reason")
        budget.stop_reason = reason
        return budget

    def soft_reached(self) -> bool:
        """True once a soft limit (background jobs only) is met: time to wrap up."""
        soft = self.soft
        return soft is not None and (
            self.model_requests >= soft.model_requests or self.tool_calls >= soft.tool_calls
            or self.tokens >= soft.tokens or time.monotonic() - self.started >= soft.wall_seconds)

    def remaining_seconds(self) -> float:
        return max(0.0, self.limits.wall_seconds - (time.monotonic() - self.started))

    def stop(self, reason: str):
        self.stop_reason = self.stop_reason or reason
        raise BudgetExceeded(f"Execution budget exhausted: {self.stop_reason}. "
                             "Saved results remain available; start a new task to continue.")

    def check(self):
        if self.stop_reason:
            self.stop(self.stop_reason)
        if self.remaining_seconds() <= 0:
            self.stop("wall_seconds")

    def model_request(self, requested_output: int) -> int:
        self.check()
        if self.model_requests >= self.limits.model_requests:
            self.stop("model_requests")
        if self.tokens >= self.limits.tokens:
            self.stop("tokens")
        self.model_requests += 1
        return min(requested_output, self.limits.output_tokens_per_request,
                   max(1, self.limits.tokens - self.tokens))

    def tool(self):
        self.check()
        if self.tool_calls >= self.limits.tool_calls:
            self.stop("tool_calls")
        self.tool_calls += 1

    def reserve_artifact(self, count: int):
        self.check()
        if self.artifact_bytes + count > self.limits.artifact_bytes:
            self.stop("artifact_bytes")
        self.artifact_bytes += count

    def snapshot(self) -> dict:
        return {"id": self.id, "limits": asdict(self.limits),
                "used": {"model_requests": self.model_requests, "tool_calls": self.tool_calls,
                         "tokens": self.tokens, "artifact_bytes": self.artifact_bytes,
                         "wall_seconds": round(time.monotonic() - self.started, 3)},
                "stop_reason": self.stop_reason,
                "token_limit_mode": "post_response_admission", "monetary_limit": False,
                **({"soft_limits": asdict(self.soft)} if self.soft is not None else {})}


_current: ContextVar[Budget | None] = ContextVar("execution_budget", default=None)


def current() -> Budget | None:
    return _current.get()


@contextmanager
def scope(budget: Budget | None = None):
    """Explicit scope. Nested execution should reuse current() rather than reset it."""
    token = _current.set(budget or Budget())
    try:
        yield _current.get()
    finally:
        _current.reset(token)


def detached_context():
    """Background maintenance gets its own budget, not a completed user's counter."""
    context = copy_context()
    context.run(_current.set, None)
    from arslan.execution_checkpoint import clear_in
    clear_in(context)
    return context


def governed(function):
    """Bound an entry point; recursion and child tasks share the SAME mutable budget."""
    @wraps(function)
    async def wrapper(*args, **kwargs):
        if current() is not None:
            current().check()
            return await function(*args, **kwargs)
        with scope() as budget:
            timeout = asyncio.timeout(budget.remaining_seconds())
            try:
                async with timeout:
                    return await function(*args, **kwargs)
            except TimeoutError:
                if timeout.expired():
                    budget.stop("wall_seconds")
                raise
    return wrapper


def model_request(requested_output: int) -> int:
    budget = current()
    return budget.model_request(requested_output) if budget else requested_output


def charge_tokens(tokens: int):
    budget = current()
    if budget:
        budget.tokens += max(0, int(tokens))
