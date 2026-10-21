"""K4b: web reads count as steps (master plan K4 ④).

Before, a live turn had its own allowance of 25 `web_search` / `web_extract` calls: past it each read
was refused, and with save tools wired the turn went to "finishing" and ended as
`task_budget_exhausted`, a budget "waiting for you". Now a read is one tool call under K4a's limits.
The eval / replay allowance (50 per attempt) is a different thing and stays.
"""
import pytest

from server.orchestrator import tool_loop
from server.services import replay_safety
from tests.server import test_trajectory_golden as golden

READS = 30


class _Pages:
    def __init__(self):
        self.n = 0

    async def execute(self, args):
        self.n += 1
        return {"ok": True, "results": [{"title": f"page {self.n}", "url": f"https://pages.example/{self.n}"}]}


async def test_thirty_web_reads_in_one_turn_all_run(monkeypatch):
    replies = [golden._Resp(None, [golden._tc("web_search", {"query": f"q{i}"}, f"s{i}")]) for i in range(READS)]
    adapter = golden._Recorder(replies + [golden._Resp("Here are the thirty pages.")])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    golden._pin_workspace(monkeypatch)
    pages = _Pages()
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", pages)
    monkeypatch.setitem(executors.EXECUTORS, "write_file", golden._Write())

    async def resolve():
        return [{"key": "web_search", "description": "search"}, {"key": "write_file", "description": "write"}]
    result = await tool_loop.run_native(system="S", user_content="read thirty pages", history=[],
                                        emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=resolve)
    assert pages.n == READS and all(item["result"]["ok"] for item in result["tool_trace"])
    assert not any("allowance" in call["user"] for call in adapter.calls)       # no "finishing" for reads
    assert result["final"] == "Here are the thirty pages."


def test_no_live_read_allowance_is_left():
    assert not hasattr(tool_loop, "LIVE_FETCH_BUDGET")


async def test_the_eval_allowance_still_refuses_at_the_dispatch_after_fifty(monkeypatch):
    sentinel = sorted(getattr(replay_safety, "_HERMETIC_CONVERSATION_IDS", ["evolution-replay"]))[0]
    tool_loop.reset_hermetic_fetch_budget(sentinel)

    async def never(*a, **k):
        raise AssertionError("the executor must not run once the eval allowance is spent")

    async def resolve():
        return [{"key": "web_extract"}]
    for _ in range(tool_loop.HERMETIC_FETCH_BUDGET):
        assert await tool_loop._check_fetch_budget("web_extract", conversation_id=sentinel) is None
    monkeypatch.setattr(tool_loop, "resolve_executor", never, raising=False)
    out = await tool_loop._dispatch_tool("web_extract", {"url": "https://example.test/x"}, "{}",
                                         resolve_tools=resolve, emit=lambda e: None, tool_timeout_s=5,
                                         tool_trace=[], convo=[], conversation_id=sentinel, log_events=False)
    assert out["ok"] is False and "evaluation fetch budget" in out["error"]
    tool_loop.reset_hermetic_fetch_budget(sentinel)


@pytest.mark.parametrize("tool", ["web_search", "web_extract"])
async def test_a_live_read_is_never_refused_for_count(tool):
    for _ in range(READS):
        assert await tool_loop._check_fetch_budget(tool, conversation_id="conv-live") is None
