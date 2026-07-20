"""C (FU-2): a per-run ceiling on outbound fetches — LIVE runs only.

🔴 SCOPE, STATED UP FRONT SO NOBODY READS THIS AS "NETWORK IS BOUNDED".
This bounds `web_search` / `web_extract` inside ONE LIVE run. The evolution EVAL path is
NOT covered and is the more dangerous of the two: a hermetic replay still exposes both web
tools (they are in REPLAY_SAFE_BUILTINS — the sealing keeps read-only web, it drops WRITE
tools and non-allowlisted ones), and the gate dispatches roughly
`pairs x 2 arms x (epochs*lr_budget + 1)` times, so one runaway candidate multiplies its
outbound requests by a few hundred. Bounding that means touching the evaluator/replay
loop, which is registered separately as FU-2b (with skill-forge folded in) and is NOT part
of this batch.

Until FU-2b lands, the honest claim is "live fetches are capped", never "network use is
capped".
"""
from __future__ import annotations

import pytest

from server.orchestrator import tool_loop
from server.services import replay_safety


# NOTE: an earlier `counted` fixture here patched a name that does not exist, counted
# nothing, and was asserted on by no test — inert scaffolding whose docstring claimed
# network isolation it did not provide. Removed. These tests reach no network because
# _check_fetch_budget makes its decision before any executor is resolved, and the one
# test that drives the real throat spends the budget first so the executor is never
# reached at all.


async def _fetch(n: int, *, conversation_id: str, budget) -> list[dict]:
    out = []
    for _ in range(n):
        out.append(await tool_loop._check_fetch_budget(
            "web_extract", conversation_id=conversation_id, budget=budget))
    return out


async def test_a_live_run_is_capped():
    """The ceiling exists and refuses past it."""
    budget: dict = {}
    verdicts = await _fetch(tool_loop.LIVE_FETCH_BUDGET + 2, conversation_id="c1", budget=budget)
    allowed = [v for v in verdicts if v is None]
    refused = [v for v in verdicts if v is not None]
    assert len(allowed) == tool_loop.LIVE_FETCH_BUDGET
    assert len(refused) == 2


async def test_the_refusal_is_explicit_not_a_silent_truncation():
    """A silently-dropped fetch would look to the model like a page with no content, and
    it would try again. Say what happened."""
    budget: dict = {}
    await _fetch(tool_loop.LIVE_FETCH_BUDGET, conversation_id="c1", budget=budget)
    refusal = await tool_loop._check_fetch_budget(
        "web_extract", conversation_id="c1", budget=budget)
    assert refusal is not None
    assert refusal["ok"] is False
    assert "budget" in refusal["error"] or "limit" in refusal["error"]
    assert str(tool_loop.LIVE_FETCH_BUDGET) in refusal["error"]


async def test_the_budget_is_PER_RUN_not_global():
    """Two runs each get the full allowance; a shared counter would starve later runs on
    a busy install for no reason."""
    a: dict = {}
    b: dict = {}
    await _fetch(tool_loop.LIVE_FETCH_BUDGET, conversation_id="c1", budget=a)
    verdict = await tool_loop._check_fetch_budget("web_extract", conversation_id="c2", budget=b)
    assert verdict is None


async def test_both_web_tools_share_one_allowance():
    """A cap on web_extract alone is trivially bypassed by alternating with web_search."""
    budget: dict = {}
    for _ in range(tool_loop.LIVE_FETCH_BUDGET):
        assert await tool_loop._check_fetch_budget(
            "web_search", conversation_id="c1", budget=budget) is None
    assert await tool_loop._check_fetch_budget(
        "web_extract", conversation_id="c1", budget=budget) is not None


async def test_non_fetch_tools_are_not_counted():
    budget: dict = {}
    for _ in range(tool_loop.LIVE_FETCH_BUDGET + 5):
        assert await tool_loop._check_fetch_budget(
            "render_chart", conversation_id="c1", budget=budget) is None


@pytest.mark.parametrize("sentinel", sorted(replay_safety._HERMETIC_CONVERSATION_IDS)
                         if hasattr(replay_safety, "_HERMETIC_CONVERSATION_IDS")
                         else ["evolution-replay"])
async def test_the_EVAL_path_is_deliberately_NOT_capped_by_this_batch(sentinel):
    """🔴 Pins the SCOPE, so the gap cannot be mistaken for coverage later.

    A hermetic replay is exempt from this ceiling — not because it is safe (it is the
    more dangerous surface: web tools stay available under sealing, and the gate
    multiplies dispatches by a few hundred) but because bounding it means touching the
    evaluator/replay loop, which is FU-2b. If someone later makes this cap apply to eval
    runs, this test failing is the signal to also delete the "live only" wording from the
    docstrings and the delivery notes.
    """
    budget: dict = {}
    verdicts = await _fetch(tool_loop.LIVE_FETCH_BUDGET + 3,
                            conversation_id=sentinel, budget=budget)
    assert all(v is None for v in verdicts), (
        "eval dispatches are out of scope for FU-2; see FU-2b")


# ── through the real throat ────────────────────────────────────────────────────────
#
# 🔴 The tests above call the helper directly. Last round an entire BLOCKER lived in the
# gap between "the helper is tested" and "the real path uses it", so this drives
# _dispatch_tool itself.


async def _dispatch(tool_key: str, *, conversation_id: str, budget: dict | None):
    frames: list[dict] = []

    async def resolve():          # _dispatch_tool awaits this
        return [{"key": tool_key}]

    return await tool_loop._dispatch_tool(
        tool_key, {"url": "https://example.test/x"}, "{}",
        resolve_tools=resolve,
        emit=frames.append, tool_timeout_s=5, tool_trace=None, convo=[],
        conversation_id=conversation_id, log_events=False, fetch_budget=budget)


async def test_the_throat_refuses_past_the_budget(monkeypatch):
    async def never(*a, **k):
        raise AssertionError("the executor must not run once the budget is spent")

    budget: dict = {"fetches": tool_loop.LIVE_FETCH_BUDGET}
    monkeypatch.setattr(tool_loop, "resolve_executor", never, raising=False)

    out = await _dispatch("web_extract", conversation_id="c1", budget=budget)
    assert out["ok"] is False
    assert str(tool_loop.LIVE_FETCH_BUDGET) in out["error"]


# NOT TESTED HERE, deliberately: "a caller that passes no fetch_budget is unaffected".
# My first attempt at it was a fake — dead code, a tautological assert, and a
# read-the-source string check — written to make the file green rather than to learn
# anything. The real regression net for that property already exists and is much
# stronger: EVERY other caller of _dispatch_tool in the suite omits fetch_budget, so if
# the cap ever applied without one, those tests go red.


# ── is the gate actually WIRED? ────────────────────────────────────────────────────


def test_run_native_creates_a_per_run_budget_and_threads_it_to_every_dispatch():
    """🔴 A budget nothing passes is a no-op dressed as a safety feature.

    I shipped exactly that in my first pass: `fetch_budget` existed on _dispatch_tool,
    the gate read it, eight occurrences in production code — and ZERO call sites passed
    it, so no real run ever reached the cap while the commit message said fetches were
    capped. Same shape as the previous round's blocker (helper tested, real path not).

    run_native is the only production tool loop (the legacy run() survives for its own
    regression tests; its docstring says so). This asserts the dict is created in
    run_native's per-invocation locals — NOT deeper, or it would reset per tool call and
    the cap would never bind — and passed at BOTH dispatch sites, including the
    force_tools proactive web_search that fires before the step loop.
    """
    import inspect

    src = inspect.getsource(tool_loop.run_native)
    assert "fetch_budget: dict[str, int] = {}" in src, (
        "run_native must own the per-run allowance")
    assert src.count("fetch_budget=fetch_budget") == 2, (
        f"expected both dispatch sites to thread the budget, found "
        f"{src.count('fetch_budget=fetch_budget')} — the proactive web_search counts too")
    # created before the proactive search, or that fetch escapes the allowance
    assert src.index("fetch_budget: dict[str, int] = {}") < src.index("fetch_budget=fetch_budget")
