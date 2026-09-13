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


class Budget:
    def __init__(self, limits: Limits | None = None):
        self.limits = limits or configured_limits()
        self.id = uuid.uuid4().hex
        self.started = time.monotonic()
        self.model_requests = 0
        self.tool_calls = 0
        self.tokens = 0
        self.artifact_bytes = 0
        self.stop_reason: str | None = None

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
                "token_limit_mode": "post_response_admission", "monetary_limit": False}


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
