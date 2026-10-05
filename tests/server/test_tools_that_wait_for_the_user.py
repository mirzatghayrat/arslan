"""A tool that waits for the user's card keeps its own time limit (0.1.53).

Measured on the user's Mac: the tool loop's 20 s default cut a Notes look while its
card was still open (twice), and an unanswered AppleScript card expired after 20 s,
so the model asked again — "it kept asking"."""
import asyncio

import pytest

from server.orchestrator import tool_loop
from server.registry import hands_tools
from server.services import approvals


class _Slow:
    def __init__(self, seconds: float, timeout_s=None):
        self.seconds = seconds
        if timeout_s is not None:
            self.timeout_s = timeout_s

    async def execute(self, args):
        await asyncio.sleep(self.seconds)
        return {"ok": True, "external": False, "text": "done"}


async def _dispatch(monkeypatch, executor, *, loop_limit: float):
    monkeypatch.setitem(tool_loop.EXECUTORS, "desktop_look", executor)

    async def resolve():
        return [{"key": "desktop_look", "description": "look"}]
    return await tool_loop._dispatch_tool(
        "desktop_look", {}, "{}", resolve_tools=resolve, emit=lambda e: None, tool_timeout_s=loop_limit,
        tool_trace=[], convo=[], conversation_id="c1")


async def test_the_loop_limit_still_stops_a_tool_that_declares_none(monkeypatch):
    result = await _dispatch(monkeypatch, _Slow(0.3), loop_limit=0.05)
    assert result["ok"] is False and "timed out" in result["error"]


async def test_a_tool_that_declares_its_own_limit_is_given_it(monkeypatch):
    result = await _dispatch(monkeypatch, _Slow(0.3, timeout_s=2), loop_limit=0.05)
    assert result["ok"] is True


async def test_its_own_limit_is_still_a_limit(monkeypatch):
    result = await _dispatch(monkeypatch, _Slow(0.5, timeout_s=0.1), loop_limit=0.05)
    assert result["ok"] is False and "timed out" in result["error"]


def test_the_card_time_matches_the_cards():
    assert hands_tools.CARD_S == approvals.TIMEOUT_S


@pytest.mark.parametrize("executor, cards", [
    (hands_tools.DesktopLookExecutor, 1), (hands_tools.DesktopClickExecutor, 2),
    (hands_tools.DesktopTypeExecutor, 2), (hands_tools.DesktopPressExecutor, 2),
    (hands_tools.MacAppleScriptExecutor, 1), (hands_tools.MacRunShortcutExecutor, 1),
    (hands_tools.BrowserClickExecutor, 1), (hands_tools.BrowserTypeExecutor, 1),
])
def test_every_tool_that_asks_outlasts_its_cards_and_its_work(executor, cards):
    assert executor.timeout_s >= cards * approvals.TIMEOUT_S + hands_tools.RUN_S
