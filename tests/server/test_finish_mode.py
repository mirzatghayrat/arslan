"""Completion first after a stop (0.1.50, S6 bench T2).

Repeated failure or a spent fetch allowance ends research, not the deliverable:
the run gets up to two steps where only the save tools run, then answers in text.
K3: those steps keep the whole tool table (Claude's cache); other calls are refused.
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


def _stuck():
    """K4a: the same failing call three times is a stuck loop (different failures don't add up)."""
    return [golden._Resp(None, [golden._tc("web_search", {"query": "jobs"}, f"s{i}")]) for i in range(3)]


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
    replies = _stuck() + [_write(), golden._Resp("Saved jobs.csv; 4 sites blocked.")]
    result, calls = await _run(monkeypatch, replies, search=_Blocked())
    # finish mode keeps the full list while the model complies (prompt cache)
    assert {"web_search", "write_file"} <= set(calls[3]["tools"])
    assert "research has stopped" in calls[3]["user"]
    assert calls[4]["tools"] is None and "The deliverable is saved" in calls[4]["user"]
    write = [r for r in result["tool_trace"] if r["tool"] == "write_file"]
    assert write and write[0]["result"]["ok"] is True          # not refused as "no progress"
    assert result["final"] == "Saved jobs.csv; 4 sites blocked."


@pytest.mark.asyncio
async def test_without_save_tools_a_stop_answers_at_once(monkeypatch):
    replies = _stuck() + [golden._Resp("Blocked everywhere.")]
    result, calls = await _run(monkeypatch, replies, search=_Blocked(), writers=False)
    assert calls[3]["tools"] is None and "Repeated actions made no progress" in calls[3]["user"]
    assert result["final"] == "Blocked everywhere."


@pytest.mark.asyncio
async def test_finish_mode_keeps_the_tool_table_and_a_second_refusal_ends_research(monkeypatch):
    # K3: the table never narrows within a turn (it renders before Claude's cached system); the
    # status says what still runs, a research call is refused with its reason, and after a second
    # refused call the next step is text only (same table, no tools) instead of looping on refusals.
    replies = _stuck() + [_search(10), _search(11), golden._Resp("Here is what I have.")]
    result, calls = await _run(monkeypatch, replies, search=_Blocked())
    assert [c["tools"] for c in calls[3:6]] == [["web_search", "write_file", "escalate"]] * 2 + [None]
    assert all("Tools that still run: write_file; any other call is refused." in c["user"] for c in calls[3:5])
    refused = [r for r in result["tool_trace"] if r["result"].get("code") in ("wrap_up", "task_no_progress")]
    assert len(refused) == 2 and result["final"] == "Here is what I have."


@pytest.mark.asyncio
async def test_a_spent_fetch_allowance_moves_to_saving(monkeypatch):
    replies = [_search(0), _search(1), _write(), golden._Resp("Saved jobs.csv.")]
    result, calls = await _run(monkeypatch, replies, search=_Fresh(), fetch_cap=2)
    assert {"web_search", "write_file"} <= set(calls[1]["tools"])
    assert "write_file" in calls[2]["tools"] and "reading allowance" in calls[2]["user"]
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


class _Spy:
    """run_command stand-in that records whether the host ran it offline."""
    def __init__(self):
        self.offline = []

    async def execute(self, args):
        from server.services import terminal_exec
        self.offline.append(terminal_exec.OFFLINE.get())
        return {"ok": True, "external": False, "summary": "processed"}


@pytest.mark.asyncio
async def test_wrapping_up_may_process_files_but_only_offline(monkeypatch):
    """S6 rerun r1: 50 jobs sat in a downloaded file, but wrap-up allowed only write
    tools. Now run_command is allowed while finishing — under the no-network wrapper."""
    spy = _Spy()
    adapter = golden._Recorder(_stuck() + [
        golden._Resp(None, [golden._tc("run_command", {"command": "python3 filter.py > jobs.csv"}, "r1")]),
        _write(), golden._Resp("Saved jobs.csv.")])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    golden._pin_workspace(monkeypatch)

    async def own():
        return True
    monkeypatch.setattr(tool_loop, "_writing_in_own_folder", own)

    async def allow(*_a, **_k):
        return True
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", _Blocked())
    monkeypatch.setitem(executors.EXECUTORS, "write_file", golden._Write())
    monkeypatch.setitem(executors.EXECUTORS, "run_command", spy)

    async def resolve():
        return [{"key": k, "description": k} for k in ("web_search", "write_file", "run_command")]
    result = await tool_loop.run_native(system="S", user_content="find jobs, save a table", history=[],
                                        emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=resolve,
                                        confirm_command=allow)
    assert spy.offline == [True]
    assert "runs without network now" in adapter.calls[3]["user"]
    assert result["final"] == "Saved jobs.csv."


@pytest.mark.asyncio
async def test_outside_wrap_up_commands_keep_the_network(monkeypatch):
    spy = _Spy()
    adapter = golden._Recorder([
        golden._Resp(None, [golden._tc("run_command", {"command": "ls"}, "r1")]), golden._Resp("done")])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    golden._pin_workspace(monkeypatch)

    async def allow(*_a, **_k):
        return True
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "run_command", spy)

    async def resolve():
        return [{"key": "run_command", "description": "shell"}]
    await tool_loop.run_native(system="S", user_content="list files", history=[], emit=lambda e: None,
                               on_chunk=lambda c: None, resolve_tools=resolve, confirm_command=allow)
    assert spy.offline == [False]


@pytest.mark.asyncio
async def test_soft_wrap_up_keeps_the_tool_table_after_a_refused_research_call(monkeypatch):
    from arslan.execution_budget import Budget, Limits, scope
    replies = [_search(0), _search(1), _search(2), _write(), golden._Resp("Saved jobs.csv.")]
    with scope(Budget(Limits(tool_calls=10), soft=Limits(tool_calls=2))):
        result, calls = await _run(monkeypatch, replies, search=_Fresh())
    assert "web_search" in calls[2]["tools"] and "Work budget nearly used" in calls[2]["user"]
    refused = [r for r in result["tool_trace"] if r["result"].get("code") == "wrap_up"]
    assert len(refused) == 1                                       # the third search did not run
    assert calls[3]["tools"] == ["web_search", "write_file", "escalate"]   # K3: the same table, refusals
    assert "Tools that still run: write_file; any other call is refused." in calls[3]["user"]
    assert result["final"] == "Saved jobs.csv."
