"""One shared budget across routing, tools, retries and nested dispatches.

Request/tool counts and wall time are hard limits. Token usage is charged when
the provider reports it (or estimated when unavailable), so its threshold gates
the NEXT request, not an exact monetary guarantee for a request already in flight.
"""
from __future__ import annotations

import asyncio
import contextlib
import math
import os
import time
import uuid
from contextlib import contextmanager
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, copy_context
from dataclasses import asdict, dataclass, replace
from functools import wraps


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class Limits:
    # K4a (v0.1.63): the "standard" tier's soft limits, for a chat turn and a background job alike.
    model_requests: int = 120
    tool_calls: int = 80
    tokens: int = 600_000
    wall_seconds: float = 1800
    # Runaway guard only (0.1.49 S5): the per-endpoint opening budget lives in
    # arslan/llm/output_budget.py; a flat 8192 here silently truncated thinking
    # models' work (kernel sample T5).
    output_tokens_per_request: int = 131_072
    artifact_bytes: int = 100 * 1024 * 1024

    def __post_init__(self):
        if any(not math.isfinite(value) or value <= 0 for value in asdict(self).values()):
            raise ValueError("execution budget limits must be positive")


# K4a (v0.1.63): one stop policy. A chat turn and a background job get the same limits: the tier the
# user picked in Settings (standard by default). Before, a chat turn had its own, smaller limits
# (32 requests / 24 tools / 128k / 600 s) and cut longer work off halfway; background jobs got these
# tiers from 0.1.43.
TIERS = {
    "lean": dict(model_requests=60, tool_calls=40, tokens=300_000, wall_seconds=900),
    "standard": dict(model_requests=120, tool_calls=80, tokens=600_000, wall_seconds=1800),
    "ample": dict(model_requests=240, tool_calls=160, tokens=1_200_000, wall_seconds=3600),
}
DEFAULT_TIER = "standard"
# Completion first: the tier is a SOFT limit. Reaching it switches the run to wrap-up (deliver from
# what it has); the hard limit, 1.5x, only stops a run that cannot stop itself.
HARD_OVER_SOFT = 1.5
# K4a: near the token limit a request still gets this many output tokens (never more than it asked
# for). M1's T2: a turn late in its budget was granted a few hundred, a thinking model spent them on
# reasoning, and the answer came back empty. Token accounting is post-response anyway, so this can
# overshoot the token limit by one answer.
MIN_OUTPUT_TOKENS = 16_384
# K4a: a per-task dollar cap, on by default (Settings → Advanced; at most MAX_USD_CAP). A run wraps up at
# cap / HARD_OVER_SOFT and stops at the cap. Only responses with a known price count (prices.usd_for_usage):
# a local model or one missing from the price table spends nothing here, and the token cap still holds.
DEFAULT_USD_CAP = 2.0
MAX_USD_CAP = 100.0
_ENV = {"model_requests": "MODEL_REQUESTS", "tool_calls": "TOOL_CALLS", "tokens": "TOKENS",
        "wall_seconds": "WALL_SECONDS", "output_tokens_per_request": "OUTPUT_TOKENS",
        "artifact_bytes": "ARTIFACT_BYTES"}


def tier_limits(tier: str = DEFAULT_TIER) -> Limits:
    """Soft limits for one run, a chat turn or a background job. An unknown tier is the default one;
    an `ARSLAN_RUN_MAX_*` environment variable overrides its value (benches and tests)."""
    base = Limits(**TIERS.get(tier, TIERS[DEFAULT_TIER]))
    values = {}
    for field, suffix in _ENV.items():
        raw = os.environ.get(f"ARSLAN_RUN_MAX_{suffix}")
        values[field] = (float(raw) if field == "wall_seconds" else int(raw)) if raw else getattr(base, field)
    return Limits(**values)


def _hard_over(soft: Limits) -> Limits:
    """The runaway stop for a soft wrap-up point (completion first)."""
    return replace(soft, model_requests=math.ceil(soft.model_requests * HARD_OVER_SOFT),
                   tool_calls=math.ceil(soft.tool_calls * HARD_OVER_SOFT),
                   tokens=math.ceil(soft.tokens * HARD_OVER_SOFT),
                   wall_seconds=soft.wall_seconds * HARD_OVER_SOFT)


def run_budget(tier: str = DEFAULT_TIER, *, usd_cap: float | None = DEFAULT_USD_CAP) -> "Budget":
    """The budget of one run, a chat turn or a background job (K4a): the tier is where it wraps up,
    1.5x stops it; the dollar cap likewise. A turn with only a hard limit aborted with an empty reply once
    it ran out (kernel bench T2, 0.1.49)."""
    soft = tier_limits(tier)
    return Budget(_hard_over(soft), soft=soft, usd_cap=usd_cap)


class Budget:
    # True when the last model_request granted fewer output tokens than were
    # asked for: a "length" cut then means "budget", not "raise the limit".
    last_output_clamped = False

    def __init__(self, limits: Limits | None = None, *, soft: Limits | None = None,
                 usd_cap: float | None = None):
        self.limits = limits or tier_limits()
        self.soft = soft
        self.usd_cap = usd_cap
        self.usd = 0.0
        self.unpriced_requests = 0
        self.id = uuid.uuid4().hex
        self.started = time.monotonic()
        self.model_requests = 0
        self.tool_calls = 0
        self.tokens = 0
        self.artifact_bytes = 0
        self.stop_reason: str | None = None
        # 0.1.63 K1: what a provider changed in the conversation before the model read it
        # (thinking blocks dropped, old tool results cleared), counts only, for the run record.
        self.context_events: list[dict] = []
        self.history: dict | None = None

    @classmethod
    def from_snapshot(cls, snapshot: dict, *, limits: Limits | None = None,
                      usd_cap: float | None = DEFAULT_USD_CAP) -> Budget:
        """Restore charged work, never reset it or silently widen its ceiling.

        Downtime is not execution time. The elapsed execution recorded before a
        crash remains charged; every new live interval starts at that offset.
        Token overrun is legal here because accounting is post-response.

        K4a: the dollar spend restores with the snapshot. A snapshot from before K4a has none: it gets
        `usd_cap` (the default cap) and spend 0 (⓪Plan's Q13).
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
        if reason is not None and reason not in {"model_requests", "tool_calls", "tokens", "artifact_bytes",
                                                 "wall_seconds", "usd"}:
            raise ValueError("invalid execution budget stop reason")
        budget.stop_reason = reason
        spend = snapshot.get("spend")
        if spend is None:
            budget.usd_cap = usd_cap
            return budget
        if not isinstance(spend, dict):
            raise ValueError("invalid execution budget spend")
        usd, cap, unpriced = spend.get("usd"), spend.get("usd_cap"), spend.get("unpriced_requests")
        if (isinstance(usd, bool) or not isinstance(usd, (int, float)) or not math.isfinite(usd) or usd < 0
                or (cap is not None and (isinstance(cap, bool) or not isinstance(cap, (int, float))
                                         or not math.isfinite(cap) or cap <= 0))
                or type(unpriced) is not int or unpriced < 0):
            raise ValueError("invalid execution budget spend")
        budget.usd, budget.usd_cap, budget.unpriced_requests = float(usd), cap, unpriced
        return budget

    def soft_reached(self) -> bool:
        """True once a soft limit (background jobs and conversational turns) is met:
        time to wrap up."""
        soft = self.soft
        return (soft is not None and (
            self.model_requests >= soft.model_requests or self.tool_calls >= soft.tool_calls
            or self.tokens >= soft.tokens or time.monotonic() - self.started >= soft.wall_seconds)
        ) or (self.usd_cap is not None and self.usd >= self.usd_cap / HARD_OVER_SOFT)

    def remaining_seconds(self) -> float:
        return max(0.0, self.limits.wall_seconds - self.elapsed())

    def elapsed(self) -> float:
        """Seconds of the run's own time: a card's wait (`paused`) moves `started` forward."""
        return time.monotonic() - self.started

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
        if self.usd_cap is not None and self.usd >= self.usd_cap:
            self.stop("usd")
        self.model_requests += 1
        granted = min(requested_output, self.limits.output_tokens_per_request,
                      max(MIN_OUTPUT_TOKENS, self.limits.tokens - self.tokens))
        self.last_output_clamped = granted < requested_output
        return granted

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

    def charge_usd(self, usd: float | None) -> None:
        """One response's price (K4a); None: a response whose price isn't known, counted, adding nothing."""
        if usd is None:
            self.unpriced_requests += 1
        else:
            self.usd += max(0.0, float(usd))

    def note_context(self, kind: str, *, reason: str, count: int) -> None:
        """One provider-side change to the conversation, at this model request (counts only)."""
        self.context_events.append({"kind": kind, "reason": reason, "count": count,
                                    "request": self.model_requests})

    def note_history(self, *, window: int, source: str, budget: int) -> None:
        """How much conversation history this run's requests may carry, and where the model's
        window came from ("table", "default", "fixed", "unresolved"), so M2 can count fallbacks (K2)."""
        self.history = {"window": window, "source": source, "budget": budget}

    def snapshot(self) -> dict:
        return {"id": self.id, "limits": asdict(self.limits),
                "used": {"model_requests": self.model_requests, "tool_calls": self.tool_calls,
                         "tokens": self.tokens, "artifact_bytes": self.artifact_bytes,
                         "wall_seconds": round(time.monotonic() - self.started, 3)},
                "stop_reason": self.stop_reason,
                "token_limit_mode": "post_response_admission", "monetary_limit": self.usd_cap is not None,
                **({"soft_limits": asdict(self.soft)} if self.soft is not None else {}),
                **({"spend": {"usd": round(self.usd, 6), "usd_cap": self.usd_cap,
                              "unpriced_requests": self.unpriced_requests}}
                   if self.usd_cap is not None or self.usd or self.unpriced_requests else {}),
                **({"context_events": list(self.context_events)} if self.context_events else {}),
                **({"history": dict(self.history)} if self.history else {})}


_current: ContextVar[Budget | None] = ContextVar("execution_budget", default=None)


def current() -> Budget | None:
    return _current.get()


class _WallClock:
    """A running wall clock: a budget and the entered timeout that enforces it. A card waiting
    for the user pauses it (`paused`, 0.1.61): the deadline moves out and the budget is credited
    by the time waited. Overlapping waits (two tasks, one clock) pause it once."""

    def __init__(self, budget: Budget, timeout: asyncio.Timeout):
        self.budget, self.timeout = budget, timeout
        self.pauses, self.paused_at, self.deadline = 0, 0.0, None

    def pause(self) -> None:
        self.pauses += 1
        if self.pauses > 1:
            return
        self.paused_at, self.deadline = time.monotonic(), None
        if not self.timeout.expired() and self.timeout.when() is not None:
            self.deadline = self.timeout.when()
            with contextlib.suppress(RuntimeError):       # the timeout is no longer running
                self.timeout.reschedule(None)

    def resume(self) -> None:
        self.pauses -= 1
        if self.pauses > 0:
            return
        waited = max(0.0, time.monotonic() - self.paused_at)
        self.budget.started += waited
        deadline, self.deadline = self.deadline, None
        if deadline is not None:
            with contextlib.suppress(RuntimeError):       # the timeout is no longer running
                self.timeout.reschedule(deadline + waited)


#: The wall clocks the current code runs under, outermost first (an entry point's, a task's).
_clocks: ContextVar[tuple[_WallClock, ...]] = ContextVar("execution_wall_clocks", default=())


@contextmanager
def running_clock(budget: Budget, timeout: asyncio.Timeout):
    """Inside an entered `asyncio.timeout` that enforces `budget`'s wall time: make it a clock
    a card's wait can pause (`paused`)."""
    token = _clocks.set(_clocks.get() + (_WallClock(budget, timeout),))
    try:
        yield
    finally:
        _clocks.reset(token)


@contextmanager
def paused():
    """Every wall clock this code runs under stands still meanwhile: the user's time is not the
    work's (0.1.61 §A4: a card waits 30 minutes; a run's clock is 30 minutes at the standard tier, 45
    at most). Nothing
    happens when no clock is running."""
    clocks = _clocks.get()
    for clock in clocks:
        clock.pause()
    try:
        yield
    finally:
        for clock in reversed(clocks):
            clock.resume()


@contextmanager
def scope(budget: Budget | None = None):
    """Explicit scope. Nested execution should reuse current() rather than reset it."""
    token = _current.set(budget or run_budget())
    try:
        yield _current.get()
    finally:
        _current.reset(token)


def detached_context():
    """Background maintenance gets its own budget, not a completed user's counter."""
    context = copy_context()
    context.run(_current.set, None)
    context.run(_clocks.set, ())
    from arslan.execution_checkpoint import clear_in
    clear_in(context)
    return context


#: How an entry point makes its run's budget (K4a): the server registers one that reads the tier the
#: user picked (settings_service.run_budget_from_settings); without one, the default tier.
_budget_factory: Callable[[], Awaitable[Budget]] | None = None


def use_budget_factory(factory: Callable[[], Awaitable[Budget]] | None) -> None:
    global _budget_factory
    _budget_factory = factory


def governed(function):
    """Bound an entry point; recursion and child tasks share the SAME mutable budget. A chat turn
    starts here, before anything has read the settings, so the budget comes from the registered
    factory (K4a: the user's tier for a chat turn as for a job)."""
    @wraps(function)
    async def wrapper(*args, **kwargs):
        if current() is not None:
            current().check()
            return await function(*args, **kwargs)
        made = await _budget_factory() if _budget_factory is not None else None
        with scope(made) as budget:
            timeout = asyncio.timeout(budget.remaining_seconds())
            try:
                async with timeout:
                    with running_clock(budget, timeout):    # a card's wait pauses it
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


def charge_usd(usd: float | None):
    budget = current()
    if budget:
        budget.charge_usd(usd)
