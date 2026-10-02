"""Completion first after a stop (0.1.50, S6 bench T2).

Repeated failure or a spent fetch allowance ends research, not the deliverable:
the run gets up to two steps offering only the save tools, then answers in text.
And the synthesis fallback keeps each finding's link."""
import pytest

from server.orchestrator import tool_loop
from tests.server import test_trajectory_golden as golden


class _Blocked:
    async def execute(self, args):
        return {"ok": False, "error": "blocked by the site"}


class _Fresh:
    def __init__(self):
        self.n = 0

    async def execute(self, args):
        self.n += 1
        return {"ok": True, "results": [{"title": f"job {self.n}", "url": f"https://jobs.example/{self.n}"}]}


def _search(i):
    return golden._Resp(None, [golden._tc("web_search", {"query": f"q{i}"}, f"s{i}")])


def _write(cid="w1"):
    return golden._Resp(None, [golden._tc("write_file", {"path": "jobs.csv", "content": "a,b"}, cid)])


async def _run(monkeypatch, replies, *, search, writers=True, fetch_cap=None):
    adapter = golden._Recorder(replies)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    golden._pin_workspace(monkeypatch)

    async def own():
        return True
    monkeypatch.setattr(tool_loop, "_writing_in_own_folder", own)
    if fetch_cap is not None:
        monkeypatch.setattr(tool_loop, "LIVE_FETCH_BUDGET", fetch_cap)
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", search)
    monkeypatch.setitem(executors.EXECUTORS, "write_file", golden._Write())

    async def resolve():
        tools = [{"key": "web_search", "description": "search"}]
        return tools + ([{"key": "write_file", "description": "write"}] if writers else [])
    result = await tool_loop.run_native(system="S", user_content="find 10 jobs and save a table", history=[],
                                        emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=resolve)
    return result, adapter.calls


@pytest.mark.asyncio
async def test_a_no_progress_stop_still_lets_the_table_be_saved(monkeypatch):
    replies = [_search(i) for i in range(4)] + [_write(), golden._Resp("Saved jobs.csv; 4 sites blocked.")]
    result, calls = await _run(monkeypatch, replies, search=_Blocked())
    assert calls[4]["tools"] == ["write_file"]                 # finish mode: save tools only
    assert "research has stopped" in calls[4]["user"]
    assert calls[5]["tools"] is None and "The deliverable is saved" in calls[5]["user"]
    write = [r for r in result["tool_trace"] if r["tool"] == "write_file"]
    assert write and write[0]["result"]["ok"] is True          # not refused as "no progress"
    assert result["final"] == "Saved jobs.csv; 4 sites blocked."


@pytest.mark.asyncio
async def test_without_save_tools_a_stop_answers_at_once(monkeypatch):
    replies = [_search(i) for i in range(4)] + [golden._Resp("Blocked everywhere.")]
    result, calls = await _run(monkeypatch, replies, search=_Blocked(), writers=False)
    assert calls[4]["tools"] is None and "Repeated actions made no progress" in calls[4]["user"]
    assert result["final"] == "Blocked everywhere."


@pytest.mark.asyncio
async def test_finish_mode_lasts_two_steps_at_most(monkeypatch):
    replies = [_search(i) for i in range(4)] + [_search(10), _search(11), golden._Resp("Here is what I have.")]
    result, calls = await _run(monkeypatch, replies, search=_Blocked())
    assert [c["tools"] for c in calls[4:7]] == [["write_file"], ["write_file"], None]
    assert result["final"] == "Here is what I have."


@pytest.mark.asyncio
async def test_a_spent_fetch_allowance_moves_to_saving(monkeypatch):
    replies = [_search(0), _search(1), _write(), golden._Resp("Saved jobs.csv.")]
    result, calls = await _run(monkeypatch, replies, search=_Fresh(), fetch_cap=2)
    assert {"web_search", "write_file"} <= set(calls[1]["tools"])
    assert calls[2]["tools"] == ["write_file"] and "reading allowance" in calls[2]["user"]
    assert calls[3]["tools"] is None
    assert result["final"] == "Saved jobs.csv."


@pytest.mark.asyncio
async def test_a_spent_fetch_allowance_without_save_tools_changes_nothing(monkeypatch):
    replies = [_search(0), _search(1), golden._Resp("done")]
    result, calls = await _run(monkeypatch, replies, search=_Fresh(), writers=False, fetch_cap=2)
    assert "web_search" in calls[2]["tools"] and "allowance" not in calls[2]["user"]
    assert result["final"] == "done"


def test_findings_keep_their_links():
    trace = [{"tool": "web_search", "args": {"query": "jobs"}, "result": {"ok": True, "results": [
                 {"title": "PM at Acme", "url": "https://jobs.example/acme", "snippet": "Shanghai, posted 1 Oct"}]}},
             {"tool": "web_extract", "args": {"url": "https://jobs.example/beta"},
              "result": {"ok": True, "text": "Beta Corp — Product Manager, Shanghai"}}]
    findings = tool_loop._clean_findings(trace)
    assert "PM at Acme <https://jobs.example/acme>: Shanghai, posted 1 Oct" in findings
    assert "[https://jobs.example/beta] Beta Corp" in findings
