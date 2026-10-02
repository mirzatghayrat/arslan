"""<agent_status> in real request bodies (0.1.50 P2 S1).

What the provider receives is the contract: the system prompt never changes
within a turn, the status is the tail of the last message, exactly once, and
never a new message — so the native trajectory keeps its shape (no extra user
turn that would make DeepSeek drop in-turn reasoning) and everything before the
last message is the same bytes as the previous request (prefix cache)."""
import copy
from pathlib import Path

import pytest

from arslan.llm import trajectory as tj
from server.orchestrator import agent_status, tool_loop
from tests.server import test_trajectory_golden as golden

PLAN = {"items": [{"text": "find sources", "status": "done"},
                  {"text": "save report", "status": "in_progress"}]}


class Resp(golden._Resp):
    def __init__(self, content=None, tool_calls=None, finish_reason=None):
        super().__init__(content, tool_calls)
        self.finish_reason = finish_reason


class NativeRecorder:
    def __init__(self, replies):
        self._r = list(replies)
        self.calls = []

    def native_trajectory(self):
        return True

    async def chat_trajectory(self, system, messages, tools=None, tool_choice=None, **kw):
        self.calls.append({"system": system, "messages": copy.deepcopy(messages),
                           "tools": None if tools is None else [t["function"]["name"] for t in tools],
                           "tool_choice": tool_choice})
        return self._r.pop(0)


async def _resolve():
    return [*(await golden._resolve()), {"key": "update_plan", "description": "plan"}]


async def _run(monkeypatch, replies, **kwargs):
    adapter = NativeRecorder(replies)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    golden._pin_workspace(monkeypatch)

    async def own():
        return True
    monkeypatch.setattr(tool_loop, "_writing_in_own_folder", own)
    from server.registry import executors
    for key, executor in {"web_search": golden._Search, "web_extract": golden._Extract,
                          "write_file": golden._Write}.items():
        monkeypatch.setitem(executors.EXECUTORS, key, executor())
    result = await tool_loop.run_native(system="SYS", user_content="research then save", history=[],
                                        emit=lambda e: None, on_chunk=lambda c: None,
                                        resolve_tools=_resolve, **kwargs)
    return result, adapter.calls


def _status_of(message: dict) -> str:
    content = message["content"]
    return content[content.rindex(agent_status.OPEN):]


def _research_turn():
    return [Resp(None, [golden._tc("update_plan", PLAN, "c1"),
                        golden._tc("web_extract", {"url": "https://example.test/a"}, "c2")]),
            Resp(None, [golden._tc("write_file", {"path": "report.md", "content": "# R"}, "c3")]),
            Resp("Saved report.md.")]


@pytest.mark.asyncio
async def test_system_prompt_is_byte_identical_and_status_is_the_tail_once(monkeypatch):
    result, calls = await _run(monkeypatch, _research_turn())
    assert result["final"] == "Saved report.md." and len(calls) == 3
    assert len({c["system"] for c in calls}) == 1 and "Text only" not in calls[-1]["system"]
    # Step 0 has done nothing yet: the request goes out exactly as written.
    assert calls[0]["messages"][-1]["content"] == "research then save"
    for call in calls[1:]:
        messages = call["messages"]
        assert messages[-1]["content"].endswith(agent_status.CLOSE)
        assert sum(str(m.get("content")).count(agent_status.OPEN) for m in messages) == 1
        tj.validate(messages)                                   # shape unchanged
        roles = [m["role"] for m in messages]
        assert ("user", "user") not in zip(roles, roles[1:])     # never a second user turn


@pytest.mark.asyncio
async def test_each_request_repeats_the_previous_one_byte_for_byte_up_to_its_status(monkeypatch):
    _, calls = await _run(monkeypatch, _research_turn())
    for before, after in zip(calls[1:], calls[2:]):
        prev, nxt = before["messages"], after["messages"]
        assert nxt[:len(prev) - 1] == prev[:-1]
        restored = nxt[len(prev) - 1]["content"] + "\n\n" + _status_of(prev[-1])
        assert restored == prev[-1]["content"]                  # same message, minus its status


@pytest.mark.asyncio
async def test_status_reports_plan_research_scope_and_saved_files_as_they_happen(monkeypatch):
    _, calls = await _run(monkeypatch, _research_turn())
    assert agent_status.OPEN not in calls[0]["messages"][-1]["content"]
    second, third = (_status_of(c["messages"][-1]) for c in calls[1:])
    assert "Workspace: ~/Arslan — your own folder" in second and "write_file" in second
    assert "Plan (your list): [x] find sources  [>] save report" in second
    assert "Research scope" in second and "Saved this turn" not in second
    assert "Saved this turn: report.md" in third
    assert "Work so far: 2 tool calls (wrap-up at" in third     # update_plan is not a tool call


@pytest.mark.asyncio
async def test_forced_step_says_why_and_hides_the_write_line(monkeypatch):
    _, calls = await _run(monkeypatch, [Resp(None, [golden._tc("web_search", {"query": "q"})]),
                                        Resp("final from forced step")], max_tool_calls=1)
    forced = calls[-1]
    assert forced["tool_choice"] == "none"
    status = _status_of(forced["messages"][-1])
    assert "Tool budget exhausted" in status and "Workspace:" not in status
    assert len({c["system"] for c in calls}) == 1 and "Text only" not in calls[-1]["system"]


@pytest.mark.asyncio
async def test_a_continued_answer_keeps_the_original_request_as_its_exact_prefix(monkeypatch):
    _, calls = await _run(monkeypatch, [Resp(None, [golden._tc("web_search", {"query": "q"})]),
                                        Resp("part one ", finish_reason="length"),
                                        Resp("part two", finish_reason="stop")])
    original, continued = calls[1]["messages"], calls[2]["messages"]
    assert original[-1]["content"].endswith(agent_status.CLOSE)
    assert continued[:len(original)] == original
    assert continued[len(original)]["role"] == "assistant"
    assert continued[-1]["content"] == tool_loop.CONTINUE_PROMPT
    assert sum(str(m.get("content")).count(agent_status.OPEN) for m in continued) == 1


@pytest.mark.asyncio
async def test_an_echoed_status_never_reaches_the_user(monkeypatch):
    echo = f"Done.\n{agent_status.OPEN}\nWorkspace: ~/Arslan\n{agent_status.CLOSE}"
    result, _ = await _run(monkeypatch, [Resp(echo)])
    assert result["final"] == "Done."


@pytest.mark.asyncio
async def test_workspace_lookup_only_when_a_writer_is_wired(monkeypatch):
    from server.db import session as db_session

    opened = []

    class Counting:
        def __call__(self):
            opened.append(1)
            raise RuntimeError("no db in this test")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Counting())
    assert await tool_loop._status_workspace({"web_search"}) == (None, False)
    assert opened == []                                   # no settings read without a writer

    class Broken:
        def __call__(self):
            raise RuntimeError("db down")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Broken())
    assert await tool_loop._status_workspace({"write_file"}) == (None, False)


@pytest.mark.asyncio
async def test_workspace_lookup_reads_the_setting(monkeypatch, tmp_path):
    from tests.server.test_workspace_tool_gate import _wire
    mine = tmp_path / "mine"
    mine.mkdir()
    engine = await _wire(tmp_path, monkeypatch, workspace=str(mine))
    assert await tool_loop._status_workspace({"run_command"}) == (Path(mine).resolve(), False)
    await engine.dispose()
