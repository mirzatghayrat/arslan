"""SMART-5 gate fixes (v0.1.64; the gate failed on length, ⓪Plan 2026-11-03).

The bench (main 14b1bd81 against OpenClaw, both on deepseek-v4-flash) found three things:
- **The four closing lines landed on answers.** K5's note asked for them after any two tool steps, so a question
  answered from two reads (my_status, then whats_new) ended with "what I did / how I checked / unverified / watch"
  (task 2: one line of answer, four of footer). The lines now come only once the turn did work: a call that
  succeeded and is not a read (`task_service.effect_of`). "These rules are for reports, not for chatting."
- **A version question was answered from the version line, with no my_status call** (task 1). The line said "use
  this line"; it now sends the model to my_status, as SMART-2's self-state rule does.
- **Guidance had a place and a command but no retry line** (tasks 9, 10). The SMART-3 rule now says the line is the
  guidance's last line, in the reply's language, and that it is there even after a workaround.
"""
import pytest

from server.orchestrator import arslan
from tests.server import test_trajectory_golden as golden
from tests.server.test_agent_status_requests import Resp, _run
from tests.server.test_k5_closing_lines import CLOSING, _status


class _Read:
    async def execute(self, args):
        return {"ok": True, "summary": "state"}


async def _turn(monkeypatch, steps):
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "read_file", _Read())     # a read the test turn is offered
    replies = [Resp(None, [golden._tc(name, args, f"c{i}")]) for i, (name, args) in enumerate(steps)]
    return await _run(monkeypatch, [*replies, Resp("Done.")])


@pytest.mark.asyncio
async def test_an_answer_from_two_reads_gets_no_closing_lines(monkeypatch):
    _, calls = await _turn(monkeypatch, [("read_file", {"path": "a.md"}), ("read_file", {"path": "b.md"})])
    assert len(calls) == 3 and not any(CLOSING in _status(c) for c in calls)


@pytest.mark.asyncio
async def test_two_web_reads_get_none_either(monkeypatch):
    _, calls = await _turn(monkeypatch, [("web_search", {"query": "q"}), ("web_extract", {"url": "https://example.test/a"})])
    assert not any(CLOSING in _status(c) for c in calls)


@pytest.mark.asyncio
async def test_once_the_turn_saved_something_the_lines_come(monkeypatch):
    _, calls = await _turn(monkeypatch, [("web_search", {"query": "q"}), ("write_file", {"path": "r.md", "content": "x"})])
    assert CLOSING in _status(calls[2])


@pytest.mark.asyncio
async def test_a_write_that_failed_is_no_work(monkeypatch):
    class _Refused:
        async def execute(self, args):
            return {"ok": False, "error": "declined"}
    monkeypatch.setattr(golden, "_Write", _Refused)                    # _run installs golden._Write itself
    _, calls = await _turn(monkeypatch, [("read_file", {"path": "a.md"}), ("write_file", {"path": "r.md", "content": "x"})])
    assert not any(CLOSING in _status(c) for c in calls)


@pytest.mark.asyncio
async def test_work_in_the_first_step_still_counts_later(monkeypatch):
    _, calls = await _turn(monkeypatch, [("write_file", {"path": "r.md", "content": "x"}),
                                         ("read_file", {"path": "a.md"}), ("read_file", {"path": "b.md"})])
    assert CLOSING in _status(calls[2]) and CLOSING in _status(calls[3])


def test_the_version_line_sends_version_questions_to_my_status():
    line = arslan._VERSION_LINE
    assert "call my_status" in line and "never answer them from this line" in line
    assert "use this line" not in line


def test_the_retry_line_ends_the_guidance_and_not_a_workaround_that_worked():
    rule = next(b for b in arslan._CAPABILITY_SELF.split("\n- ") if "When the environment blocks you" in b)
    assert "end the guidance with one line in the reply's language: 'Tell me when it's done and I'll retry.'" in rule
    assert "Any closing lines come after it." in rule
    assert "When a way around the block already worked, there is nothing to retry: leave the line out." in rule
    assert "even when you found a way around it" not in rule


def _trace(*tools):
    return [{"tool": tool, "args": {}, "result": {"ok": True}} for tool in tools]


@pytest.mark.asyncio
async def test_searching_finding_and_probing_are_not_work():
    """#701 review: effect_of calls these external writes (it also decides retries); for the closing lines they look."""
    from server.orchestrator import tool_loop
    trace = _trace("conversation_search", "find_capability", "scan_local_network", "ssh_probe")
    assert await tool_loop._did_work(trace, {"done": False, "seen": 0}) is False
    assert await tool_loop._did_work(_trace("ssh_run"), {"done": False, "seen": 0}) is True


@pytest.mark.asyncio
async def test_a_call_whose_effect_cant_be_judged_counts_as_work(monkeypatch):
    from server.orchestrator import tool_loop
    from server.services import task_service

    async def broken(tool, args):
        raise RuntimeError("no tools table")
    monkeypatch.setattr(task_service, "effect_of", broken)
    assert await tool_loop._did_work(_trace("mcp_4__fetch"), {"done": False, "seen": 0}) is True


# -- Round 2 of the gate (3 repeats): still behind on length, 15/33 against 20/33 ------------------------------------

@pytest.mark.asyncio
async def test_finding_a_tool_and_reading_arslans_own_state_are_not_work():
    """A version question goes find_tools, then my_status. That is two steps, and find_tools wasn't a read, so one-line
    answers got four more lines (tasks 1 and 2). Reading Arslan's own state is looking too."""
    from server.orchestrator import tool_loop
    trace = _trace("find_tools", "my_status", "whats_new", "list_my_capabilities")
    assert await tool_loop._did_work(trace, {"done": False, "seen": 0}) is False


def test_the_closing_lines_step_aside_for_an_answer():
    """A command can't always be told from a read (a GET with curl), so the note says so itself (tasks 3, 4 and 5)."""
    from server.orchestrator import tool_loop
    assert "Skip them if the user asked a question and you only looked things up to answer it" in tool_loop._CLOSING_NOTE


def _report_rule() -> str:
    return next(b for b in arslan._CAPABILITY_SELF.split("\n- ") if "lead with the outcome, then the reason" in b)


def test_answer_first_holds_after_looking_things_up():
    rule = _report_rule()
    assert "Looking things up doesn't change that: the reply is still the answer to what was asked, not all you found." in rule
    assert rule.index("a short question gets one to three sentences") < rule.index("Looking things up doesn't change that")


def test_a_correction_gets_the_admission_and_a_short_right_answer():
    rule = _report_rule()
    assert "give the right answer in one or two sentences, not a new report or a list" in rule
