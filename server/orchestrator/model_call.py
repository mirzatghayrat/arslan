"""Recovery for run_native's main model call (0.1.49 P1, design sections 5.2 and 6).

Scope: ONLY the one model call each run_native step makes. Auxiliary calls
(synthesis, salvage, review) keep tool_loop._chat_retry's single fast retry:
they must give up rather than crowd the main path.

Only provider/transport failures are classified and wrapped in ModelCallError.
Runtime control (BudgetExceeded, TaskError) and programming errors propagate
unchanged; nothing here calls a model on an error path except the one bounded
re-send each recovery is for.
"""
from __future__ import annotations

import asyncio
import email.utils
import random
import re
import time
from dataclasses import dataclass, field

import httpx

# Injectable for tests (fake clock / no real waiting).
sleep = asyncio.sleep
jitter = random.random

MAX_SERVER_RETRIES = 4        # 429 / 5xx / connection: 1, 2, 4, 8 s (+0-50% jitter)
MAX_STALL_RETRIES = 1         # our own timeout: a long generation would likely time out again, billed
MAX_RETRY_AFTER_S = 60.0
TURN_RECOVERY_LIMIT = 8       # every recovery in one turn, all kinds together
# Outer bound per attempt (always also capped by the work budget). A stalled
# stream is caught much sooner by the idle watchdog (stream_assembly.IDLE_S);
# a non-streamed reply is bounded by httpx's 300 s first-byte timeout.
CALL_TIMEOUT_S = 600.0

_BALANCE = re.compile(r"insufficient[_ ](balance|quota|credits|funds)|payment required", re.I)
_CONTEXT = re.compile(r"context[_ ]length|maximum context|context window|too many tokens|"
                      r"prompt is too long|reduce the length", re.I)
# A compatible endpoint that rejects the native history (or tool_choice on a
# forced step) is answered with the legacy rendering, not a failed turn.
_PROTOCOL = re.compile(r"reasoning_content|tool_call_id|tool_calls|tool_choice|role.{0,12}tool", re.I)


@dataclass
class TurnRecovery:
    """Per-turn recovery state and breaker counts (one run_native invocation)."""
    recoveries: list[str] = field(default_factory=list)
    legacy: bool = False
    reason: str = ""
    context_retry_used: bool = False
    output_raises: int = 0
    continuations: int = 0
    truncated_calls: int = 0
    capability_bounced: bool = False   # 0.1.50: one capability-truth correction per turn

    @property
    def exhausted(self) -> bool:
        return len(self.recoveries) >= TURN_RECOVERY_LIMIT

    def note(self, what: str) -> None:
        self.recoveries.append(what)


class ModelCallError(Exception):
    """A main model call that could not be recovered. Never has an empty message:
    it always carries the class, the provider's own words and what was tried."""

    def __init__(self, kind: str, *, status: int | None, excerpt: str, attempts: int,
                 waited_s: float, recoveries: list[str]):
        self.kind, self.status, self.excerpt = kind, status, excerpt
        self.attempts, self.waited_s, self.recoveries = attempts, waited_s, list(recoveries)
        super().__init__(self._message())

    def _message(self) -> str:
        status = f" HTTP {self.status}" if self.status else ""
        tried = f"{self.attempts} attempt{'s' if self.attempts != 1 else ''}"
        if self.waited_s >= 1:
            tried += f" over {self.waited_s:.0f}s"
        extra = f"; recoveries: {', '.join(self.recoveries)}" if self.recoveries else ""
        return f"Model request failed ({self.kind}{status}): {self.excerpt}. Tried {tried}{extra}."


def classify(exc: BaseException) -> tuple[str, int | None] | None:
    """(kind, status) for a provider/transport failure; None for anything else."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        text = str(exc)
        if status == 402 or _BALANCE.search(text):
            return "balance", status
        if status in (401, 403):
            return "auth", status
        if status in (400, 413, 422) and _CONTEXT.search(text):
            return "context", status
        if status in (400, 422) and _PROTOCOL.search(text):
            return "protocol", status
        if status == 429:
            return "rate", status
        if status in (408, 425, 500, 502, 503, 504, 529):
            return "server", status
        return "input", status
    if isinstance(exc, httpx.TimeoutException | httpx.NetworkError | httpx.RemoteProtocolError):
        return "server", None
    if isinstance(exc, TimeoutError):
        return "stall", None
    return None


def retry_after(exc: BaseException) -> float | None:
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    raw = exc.response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        parsed = email.utils.parsedate_to_datetime(raw) if raw else None
        if parsed is None:
            return None
        return max(0.0, parsed.timestamp() - time.time())


def _excerpt(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    return (text or type(exc).__name__)[:500]


async def call_with_recovery(request, state: TurnRecovery, *, remaining_s=None):
    """Run request() (a zero-arg coroutine factory) with classified retries.

    Retries rate/server failures with backoff (Retry-After honoured), our own
    timeout once; never retries balance/auth/input/context/protocol (the caller
    owns context compaction and protocol degradation). Waiting never exceeds
    the remaining wall budget; the per-turn breaker bounds everything."""
    attempts, waited = 0, 0.0
    server_retries = stall_retries = 0
    while True:
        attempts += 1
        try:
            limit = CALL_TIMEOUT_S
            if remaining_s is not None:
                limit = max(1.0, min(limit, remaining_s()))
            return await asyncio.wait_for(request(), timeout=limit)
        except Exception as exc:  # noqa: BLE001 — classified below; others re-raised untouched
            found = classify(exc)
            if found is None:
                raise
            kind, status = found
            delay = None
            if kind in ("rate", "server") and server_retries < MAX_SERVER_RETRIES:
                server_retries += 1
                hinted = retry_after(exc)
                delay = (min(hinted, MAX_RETRY_AFTER_S) if hinted is not None
                         else 2 ** (server_retries - 1) * (1 + 0.5 * jitter()))
            elif kind == "stall" and stall_retries < MAX_STALL_RETRIES:
                stall_retries += 1
                delay = 0.0
            if delay is not None and remaining_s is not None and delay >= remaining_s() - 1:
                delay = None   # waiting would outlive the work budget
            if delay is None or state.exhausted:
                raise ModelCallError(kind, status=status, excerpt=_excerpt(exc), attempts=attempts,
                                     waited_s=waited, recoveries=state.recoveries) from exc
            state.note(f"retried after {kind}{f' {status}' if status else ''}")
            await sleep(delay)
            waited += delay
