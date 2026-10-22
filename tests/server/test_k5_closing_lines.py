"""K5: after a multi-step task the reply ends with four plain lines (card K5, ⓪Plan's Q5/Q6).

The four lines are what was done, how it was checked, what was not checked, and what to watch.
- **When:** once the turn has had two or more steps whose calls are not only update_plan. Plain chat and
  one-step tool turns never get it.
- **Who:** only Arslan's own turns (chat, background jobs), never a delegated worker, which answers in JSON.
- **Where:** only in the step's status block, never in the system text.
- **Wording:** what wasn't checked is written as "unverified" in the reply's language (未核对), never 没查到,
  which the search-claim guard reads as a claim to have searched (K8 fixes that pattern).
"""
import pytest

from server.orchestrator import agent_status, tool_loop
from server.orchestrator.tool_caller import ToolCaller
from tests.server import test_trajectory_golden as golden
from tests.server.test_agent_status_requests import PLAN, Resp, _research_turn, _run

CLOSING = "End your final reply with four short lines"


def _status(call) -> str:
    content = call["messages"][-1]["content"]
    content = content if isinstance(content, str) else str(content)
    return content[content.rindex(agent_status.OPEN):] if agent_status.OPEN in content else ""


@pytest.mark.asyncio
async def test_after_two_tool_steps_the_next_request_asks_for_the_four_lines(monkeypatch):
    result, calls = await _run(monkeypatch, _research_turn())          # extract, then save, then answer
    assert result["final"] == "Saved report.md." and len(calls) == 3
    assert CLOSING not in _status(calls[1]) and CLOSING in _status(calls[2])
    assert all(CLOSING not in str(c["system"]) for c in calls)
    note = _status(calls[2])
    assert "what you did" in note and "how you checked it" in note and "what the user should watch" in note
    assert "未核对" in note and "没查到" not in note


@pytest.mark.asyncio
async def test_a_one_step_tool_turn_never_gets_it(monkeypatch):
    _, calls = await _run(monkeypatch, [Resp(None, [golden._tc("web_search", {"query": "q"})]), Resp("done")])
    assert not any(CLOSING in _status(c) for c in calls)


@pytest.mark.asyncio
async def test_a_plain_chat_never_gets_it(monkeypatch):
    _, calls = await _run(monkeypatch, [Resp("hello")])
    assert len(calls) == 1 and CLOSING not in str(calls[0]["messages"])


@pytest.mark.asyncio
async def test_a_step_that_only_updates_the_plan_does_not_count(monkeypatch):
    _, calls = await _run(monkeypatch, [Resp(None, [golden._tc("update_plan", PLAN, "p1")]),
                                        Resp(None, [golden._tc("web_search", {"query": "q"}, "s1")]),
                                        Resp("done")])
    assert not any(CLOSING in _status(c) for c in calls)


@pytest.mark.asyncio
async def test_a_delegated_worker_never_gets_it(monkeypatch):
    _, calls = await _run(monkeypatch, _research_turn(), caller=ToolCaller(actor="spawn", spawn_id=7, conversation_id="c-worker"))
    assert not any(CLOSING in _status(c) for c in calls)


def test_neither_unverified_nor_not_found_is_read_as_a_search_claim():
    assert not tool_loop._CLAIMS_SEARCH_RE.search("未核对：价格")
    assert not tool_loop._CLAIMS_SEARCH_RE.search("没查到价格")   # K8a fixed it: nothing found is no claim
