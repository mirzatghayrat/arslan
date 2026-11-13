"""Completion first at the hard stop (0.1.50, S6 bench T2 r2): a chat turn that
did real work ends with a host-written closing message, not an error."""
import pytest

from arslan.execution_budget import Budget, BudgetExceeded, Limits, current, scope
from arslan.models import LLMResponse
from server.orchestrator import tool_loop
from tests.server import test_trajectory_golden as golden
from server.orchestrator import tool_gates


class _Counting:
    """Charges one model request per call, like the real adapter."""
    def __init__(self, replies):
        self._r = list(replies)

    async def chat(self, system, user, history=None, tools=None, **kw):
        current().model_request(100)
        return self._r.pop(0)


def _write():
    return LLMResponse(usage={}, content=None, tool_calls=[golden._tc("write_file", {"path": "jobs.csv", "content": "a"}, "w1")])


def _search(i):
    return LLMResponse(usage={}, content=None, tool_calls=[golden._tc("web_search", {"query": f"q{i}"}, f"s{i}")])


async def _run(monkeypatch, replies, **kwargs):
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _Counting(replies))
    golden._pin_workspace(monkeypatch)

    async def own():
        return True
    monkeypatch.setattr(tool_gates, "_writing_in_own_folder", own)
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "write_file", golden._Write())
    monkeypatch.setitem(executors.EXECUTORS, "web_search", golden._Search())
    from server.services import runtime_messages

    async def en():
        return "en"
    monkeypatch.setattr(runtime_messages, "selected_locale", en)

    async def resolve():
        return [{"key": "web_search", "description": "s"}, {"key": "write_file", "description": "w"}]
    chunks = []
    with scope(Budget(Limits(model_requests=2))):
        result = await tool_loop.run_native(system="S", user_content="jobs table", history=[],
                                            emit=lambda e: None, on_chunk=chunks.append,
                                            resolve_tools=resolve, **kwargs)
    return result, "".join(chunks)


@pytest.mark.asyncio
async def test_a_hard_stop_after_saving_ends_with_what_was_saved(monkeypatch):
    result, streamed = await _run(monkeypatch, [_write(), _search(1)])
    assert result["final"] == streamed
    assert "work limit (model requests)" in streamed and "Saved: jobs.csv (~/Arslan)" in streamed
    assert result["stop_reason"] == "task_budget_exhausted"


@pytest.mark.asyncio
async def test_a_real_chat_turn_gets_the_closing_message_too(monkeypatch):
    """The chat path passes ToolCaller(actor="host") (arslan.py); 0.1.50 checked for no
    caller at all, so a real chat turn never reached the closing message."""
    from server.orchestrator.tool_caller import ToolCaller
    result, _ = await _run(monkeypatch, [_write(), _search(1)],
                           caller=ToolCaller(actor="host", spawn_id=None, conversation_id="c"))
    assert result["stop_reason"] == "task_budget_exhausted" and result["final"]


@pytest.mark.asyncio
async def test_a_hard_stop_with_only_reading_says_nothing_was_saved(monkeypatch):
    result, _ = await _run(monkeypatch, [_search(0), _search(1)])
    assert "Nothing was saved yet" in result["final"]


@pytest.mark.asyncio
async def test_workers_and_jobs_still_raise(monkeypatch):
    from server.orchestrator.tool_caller import ToolCaller
    with pytest.raises(BudgetExceeded):
        await _run(monkeypatch, [_write(), _search(1)],
                   caller=ToolCaller(actor="worker", spawn_id=None, conversation_id="c"))
    from server.services import background_jobs
    monkeypatch.setattr(background_jobs, "inside_job", lambda: True)
    with pytest.raises(BudgetExceeded):
        await _run(monkeypatch, [_write(), _search(1)])


@pytest.mark.asyncio
async def test_no_work_done_ends_with_blocked_and_left_not_an_error(monkeypatch):
    """Until #896 a chat turn the cap stopped with no successful call raised BudgetExceeded and showed nothing.
    It now ends with the closing and the records (Blocked / Left), with no model request past the cap."""
    class _Refused:
        async def execute(self, args):
            return {"ok": False, "error": "Arslan never runs this search"}
    from server.registry import executors
    from server.services import runtime_messages

    async def en():
        return "en"
    monkeypatch.setattr(runtime_messages, "selected_locale", en)
    monkeypatch.setitem(executors.EXECUTORS, "web_search", _Refused())
    class _Attempts(_Counting):
        attempts = 0

        async def chat(self, *args, **kwargs):
            self.attempts += 1      # before admission: a refused extra request counts too
            return await super().chat(*args, **kwargs)
    adapter = _Attempts([_search(0), _search(1), _search(2)])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    chunks = []
    budget = Budget(Limits(model_requests=2))
    with scope(budget):
        async def resolve():
            return [{"key": "web_search", "description": "s"}]
        result = await tool_loop.run_native(system="S", user_content="find the jobs", history=[],
                                            emit=lambda e: None, on_chunk=chunks.append, resolve_tools=resolve)
    assert adapter.attempts == budget.model_requests == 2 and len(adapter._r) == 1, "no model request past the cap"
    assert result["stop_reason"] == "task_budget_exhausted" and result["final"] == "".join(chunks)
    final = result["final"]
    assert "work limit (model requests)" in final and "Done: no tool call succeeded." in final
    assert "Blocked:" in final and "web_search `q0`" in final
    assert final.endswith("Left: the request itself, find the jobs")
