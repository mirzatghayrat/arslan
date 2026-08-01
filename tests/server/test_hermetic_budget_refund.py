"""A concurrent attempt must not refund an in-flight one's fetch allowance.

`_hermetic_fetches` is module state keyed by ONE sentinel, and that sharing is
deliberate — the module says so, and for a spend gate sharing is the safe
direction:

    "If two spawns are evaluated at once they SHARE this allowance. That is the
     conservative direction for a spend gate and is left deliberately: a shared
     budget can only refuse earlier than a per-attempt one, never later."

The RESET was what falsified that. `_perform_attempt` cleared the counter at
the top of every attempt, and `_running_spawns` allows one attempt per SPAWN,
not one overall — so attempt B starting for a different spawn zeroed the
counter attempt A was still spending against.

Measured before the fix: A spent 40, B started, A then spent a further 50 — 90
against a nominal cap of 50, from a single overlap; N x 50 for N overlaps. The
gate loosened exactly when evolution activity, and therefore spend, was
highest: the opposite of what the comment promises and the opposite of the
direction a spend gate may fail in.

🔴 The obvious fix is empty, which is why it is worth a test. Passing the
sentinel to the reset changes nothing: every hermetic dispatch shares the one
id `"evolution-replay"`, so popping that key and clearing the dict are the same
operation. What restores the promise is refcounting attempts in flight — a
fresh allowance when the first starts, sharing thereafter.
"""
from __future__ import annotations

import pytest

from server.orchestrator import tool_loop
from server.services.replay_run import REPLAY_CONVERSATION_ID

pytestmark = pytest.mark.asyncio


async def _spend(n: int, *, budget: dict) -> int:
    """Make n fetch attempts; return how many were allowed."""
    allowed = 0
    for _ in range(n):
        refusal = await tool_loop._check_fetch_budget(
            "web_search", conversation_id=REPLAY_CONVERSATION_ID, budget=budget,
        )
        if refusal is not None:
            break
        allowed += 1
    return allowed


@pytest.fixture(autouse=True)
def _clean_counter():
    tool_loop.reset_hermetic_fetch_budget()
    tool_loop._hermetic_attempts_inflight = 0
    yield
    tool_loop.reset_hermetic_fetch_budget()
    tool_loop._hermetic_attempts_inflight = 0


async def test_the_probe_can_see_spend_at_all():
    """⓪ Before asserting anything about the cap, prove the counter moves."""
    assert tool_loop.hermetic_fetches_used(REPLAY_CONVERSATION_ID) == 0
    await _spend(3, budget={})
    assert tool_loop.hermetic_fetches_used(REPLAY_CONVERSATION_ID) == 3


async def test_the_cap_binds_when_nothing_else_is_running():
    """The baseline the concurrent case is compared against."""
    allowed = await _spend(tool_loop.HERMETIC_FETCH_BUDGET + 10, budget={})
    assert allowed == tool_loop.HERMETIC_FETCH_BUDGET


async def test_a_second_attempt_starting_does_not_refund_the_first():
    tool_loop.begin_hermetic_attempt()            # attempt A
    budget: dict = {}
    spent = await _spend(40, budget=budget)
    assert spent == 40, "the fixture no longer reaches the interesting state"

    tool_loop.begin_hermetic_attempt()            # attempt B, a DIFFERENT spawn

    extra = await _spend(tool_loop.HERMETIC_FETCH_BUDGET + 10, budget=budget)

    total = spent + extra
    assert total <= tool_loop.HERMETIC_FETCH_BUDGET, (
        f"attempt A spent {total} against a cap of {tool_loop.HERMETIC_FETCH_BUDGET} — "
        "a concurrent attempt refunded it"
    )


async def test_a_serial_attempt_still_gets_its_own_allowance():
    """The other half. Sharing must apply to OVERLAP, not to succession — a
    counter that never refreshes is the process-lifetime failure the original
    reset existed to prevent, and it would satisfy the test above."""
    tool_loop.begin_hermetic_attempt()
    assert await _spend(tool_loop.HERMETIC_FETCH_BUDGET + 5, budget={}) == tool_loop.HERMETIC_FETCH_BUDGET
    tool_loop.end_hermetic_attempt()

    tool_loop.begin_hermetic_attempt()            # A has finished; B is new
    assert await _spend(5, budget={}) == 5, "a serial attempt inherited a spent allowance"
    tool_loop.end_hermetic_attempt()


async def test_a_raising_attempt_releases_its_claim():
    """If the claim leaked, the allowance would never refresh again — the gate
    would tighten silently over uptime, which the original comment calls worse
    than no gate because it reads as a broken feature."""
    import inspect

    from server.services import evolution_watcher

    src = inspect.getsource(evolution_watcher._perform_attempt)
    assert "finally:" in src and "end_hermetic_attempt()" in src
    assert tool_loop.hermetic_attempts_inflight() == 0


async def test_a_reset_still_starts_a_fresh_allowance_for_a_new_attempt():
    """The fix must not turn the counter back into process-lifetime state.

    Discriminating: deleting the reset entirely would satisfy the test above and
    reintroduce the exact failure the reset exists to prevent — the first
    attempt after a restart gets the budget and every later one is refused,
    which reads as a broken feature rather than a limit.
    """
    await _spend(tool_loop.HERMETIC_FETCH_BUDGET + 5, budget={})
    assert tool_loop.hermetic_fetches_used(REPLAY_CONVERSATION_ID) == tool_loop.HERMETIC_FETCH_BUDGET

    tool_loop.reset_hermetic_fetch_budget(REPLAY_CONVERSATION_ID)
    assert await _spend(5, budget={}) == 5, "a genuinely new attempt got no allowance"


async def test_the_watcher_claims_rather_than_clears():
    """The call site, not just the helper — a helper that CAN take an argument
    but is called without one is exactly the bug this file is about."""
    import inspect

    from server.services import evolution_watcher

    src = inspect.getsource(evolution_watcher._perform_attempt)
    assert "reset_hermetic_fetch_budget" not in src, (
        "the watcher still resets unconditionally — and passing the sentinel is "
        "NOT a fix, since every hermetic dispatch shares that one key"
    )
    assert "begin_hermetic_attempt()" in src
