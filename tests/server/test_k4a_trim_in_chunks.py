"""K4a gate (⓪Plan's DeepSeek run, T2): on a provider that doesn't clear old results itself, the in-turn history
was trimmed to a fixed bound every step. Once a long research turn passed it, each step dropped the oldest
message, so the start of the history changed on every request and DeepSeek's prefix cache missed everything
after the system prompt (about 60k uncached tokens a step; the bench meter's $0.45 cap stopped two runs).
Now, once over the bound, the history is trimmed down to half of it in one go: the cached prefix breaks once
per chunk, and the steps in between only append.
"""
import pytest

from server.orchestrator import tool_loop
from tests.server import test_agent_status_requests as status_requests
from tests.server import test_trajectory_golden as golden


class _Big:
    def __init__(self):
        self.n = 0

    async def execute(self, args):
        self.n += 1
        return {"ok": True, "external": False, "summary": f"result {self.n} " + "y" * 1_500}


async def _run(monkeypatch, steps):
    replies = [status_requests.Resp(None, [golden._tc("web_search", {"query": f"q{i}"}, f"c{i}")])
               for i in range(steps)] + [status_requests.Resp("Done.")]
    adapter = status_requests.NativeRecorder(replies)                # no _provider: does not clear server-side
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    monkeypatch.setattr(tool_loop, "_IN_TURN_CHARS", 9_000)
    golden._pin_workspace(monkeypatch)
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", _Big())

    async def resolve():
        return [{"key": "web_search", "description": "search"}]
    result = await tool_loop.run_native(system="SYS", user_content="research", history=[],
                                        emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=resolve)
    assert result["final"] == "Done."
    return [call["messages"] for call in adapter.calls]


def _prefix_breaks(requests):
    """Requests whose messages before the last aren't the previous request's (its last differs by status)."""
    return sum(1 for before, after in zip(requests, requests[1:]) if after[:len(before) - 1] != before[:-1])


@pytest.mark.asyncio
async def test_a_long_turn_trims_its_history_in_chunks_so_most_steps_only_append(monkeypatch):
    requests = await _run(monkeypatch, steps=14)
    breaks = _prefix_breaks(requests)
    assert 1 <= breaks <= 3, breaks                                   # sliding by one message: about 10
