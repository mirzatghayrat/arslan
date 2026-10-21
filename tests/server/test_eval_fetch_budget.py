"""FU-2b: the eval/replay fetch allowance, HERMETIC_FETCH_BUDGET per attempt.

0.1.63 K4b deleted the live per-run allowance (25 web_search/web_extract calls): a live web read is one
tool call under the run's limits (tests/server/test_k4b_web_reads.py). What stays is this one. A hermetic
replay still exposes both web tools (they are in REPLAY_SAFE_BUILTINS), and the gate dispatches roughly
`pairs x 2 arms x (epochs*lr_budget + 1)` times, so the allowance spans the whole attempt.
"""
from __future__ import annotations

import pytest

from server.orchestrator import tool_loop
from server.services import replay_safety


async def _fetch(n: int, *, conversation_id: str, tool: str = "web_extract") -> list[dict]:
    out = []
    for _ in range(n):
        out.append(await tool_loop._check_fetch_budget(tool, conversation_id=conversation_id))
    return out


async def test_non_fetch_tools_are_not_counted():
    tool_loop.reset_hermetic_fetch_budget("evolution-eval")
    for _ in range(tool_loop.HERMETIC_FETCH_BUDGET + 5):
        assert (await _fetch(1, conversation_id="evolution-eval", tool="render_chart"))[0] is None
    assert tool_loop.hermetic_fetches_used("evolution-eval") == 0


@pytest.mark.parametrize("sentinel", sorted(replay_safety._HERMETIC_CONVERSATION_IDS)
                         if hasattr(replay_safety, "_HERMETIC_CONVERSATION_IDS")
                         else ["evolution-replay"])
async def test_the_eval_path_is_capped_across_the_whole_attempt(sentinel):
    """FU-2b: the eval surface is now bounded too, and NOT per dispatch.

    This test used to assert the opposite — that eval was deliberately exempt —
    and its docstring said its failure would be the signal to update the "live
    only" wording everywhere. It did not fail when the cap landed, because it
    probed only the old live allowance + 3 fetches while the new hermetic
    allowance is larger. A canary that only sings below one threshold is not a canary, so
    it now asserts the real boundary: exactly HERMETIC_FETCH_BUDGET through, and
    the next one refused.

    The allowance spans the ATTEMPT rather than the dispatch on purpose. The
    gate dispatches a few hundred times per candidate, so a per-dispatch ceiling
    would multiply rather than limit.
    """
    tool_loop.reset_hermetic_fetch_budget(sentinel)
    verdicts = await _fetch(tool_loop.HERMETIC_FETCH_BUDGET + 2, conversation_id=sentinel)

    allowed = [v for v in verdicts if v is None]
    refused = [v for v in verdicts if v is not None]
    assert len(allowed) == tool_loop.HERMETIC_FETCH_BUDGET, (
        f"expected exactly {tool_loop.HERMETIC_FETCH_BUDGET} fetches through, "
        f"got {len(allowed)}")
    assert len(refused) == 2
    assert "evaluation fetch budget" in refused[0]["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("sentinel", ["evolution-eval", "evolution-replay"])
async def test_the_eval_allowance_does_not_reset_between_dispatches(sentinel):
    """The whole point, stated as the thing that would break it.

    Each dispatch is separate; if the eval cap were kept per dispatch it would
    reset a few hundred times per candidate and bound nothing at all."""
    tool_loop.reset_hermetic_fetch_budget(sentinel)
    for _ in range(tool_loop.HERMETIC_FETCH_BUDGET):
        await _fetch(1, conversation_id=sentinel)   # one dispatch at a time
    verdict = (await _fetch(1, conversation_id=sentinel))[0]
    assert verdict is not None, (
        "a new dispatch reset the attempt allowance")


@pytest.mark.asyncio
async def test_a_new_attempt_starts_with_a_fresh_allowance():
    """Otherwise the counter is process-lifetime: the first attempt after a
    restart gets the budget and every later one gets nothing, which reads as a
    broken feature rather than a limit."""
    tool_loop.reset_hermetic_fetch_budget("evolution-eval")
    await _fetch(tool_loop.HERMETIC_FETCH_BUDGET + 1,
                 conversation_id="evolution-eval")
    assert tool_loop.hermetic_fetches_used("evolution-eval") >= tool_loop.HERMETIC_FETCH_BUDGET

    tool_loop.reset_hermetic_fetch_budget("evolution-eval")
    assert tool_loop.hermetic_fetches_used("evolution-eval") == 0
    assert (await _fetch(1, conversation_id="evolution-eval"))[0] is None
