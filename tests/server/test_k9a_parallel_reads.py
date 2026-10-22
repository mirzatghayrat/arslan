"""K9a: consecutive read-only calls of one reply run together (card K9; ⓪Plan's answers in the K9 plan).

Driven through the real run_native and _dispatch_tool, with executors that log when they start and end:
- two or more allowlisted reads in a row overlap (at most 4 at once); a call that is not on the list
  (a write, anything else) runs alone, in its place (Q2);
- every gate still runs per call, in the reply's order: a refused fetch budget lands on the same call;
- the frames, the trace and the history keep the reply's order and pairing, whatever finished first (Q3);
- two calls to one MCP server never overlap; a server that does not say it only reads is not a read;
- `tools_serial` runs everything one at a time again (Q4; DELETE-BY v0.1.64);
- stopping the turn stops every call of the group.
"""
import asyncio
import json

import pytest

from arslan import execution_budget
from arslan.models import LLMResponse
from server.db.models import MCPServer, Setting, Tool, Toolset
from server.orchestrator import parallel_reads, tool_loop


class _Log:
    def __init__(self):
        self.events: list[tuple[str, str]] = []
        self.running = 0
        self.most = 0
        self.frames: list[dict] = []
        self.both = asyncio.Event()


class _Read:
    """A tool that takes `delay` seconds; with `meet`, it waits (up to 5 s) until `meet` calls run at once."""

    def __init__(self, log: _Log, delay: float = 0.02, meet: int = 0, forever: bool = False):
        self.log, self.delay, self.meet, self.forever = log, delay, meet, forever
        self.cancelled: list[str] = []

    async def execute(self, args):
        tag = str(args.get("path") or args.get("tag"))
        log = self.log
        log.events.append(("start", tag))
        log.running += 1
        log.most = max(log.most, log.running)
        try:
            if self.forever:
                await asyncio.Event().wait()
            if self.meet:
                if log.running >= self.meet:
                    log.both.set()
                try:
                    await asyncio.wait_for(log.both.wait(), timeout=5)
                except TimeoutError:
                    return {"ok": False, "error": f"{tag} ran alone"}
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled.append(tag)
            raise
        finally:
            log.running -= 1
        log.events.append(("end", tag))
        return {"ok": True, "text": f"result of {tag}"}


def _call(index: int, name: str, args: dict) -> dict:
    return {"id": f"c{index}", "type": "function", "function": {"name": name, "arguments": args}}


class _Script:
    """One reply with these calls, then an answer."""

    def __init__(self, *calls: tuple[str, dict]):
        self.calls = list(calls)
        self.requests: list[list] = []

    async def chat(self, system, user, history=None, **kwargs):
        self.requests.append([*(history or []), {"role": "user", "content": user}])
        if len(self.requests) == 1:
            return LLMResponse(content="", usage={}, tool_calls=[_call(i, n, a) for i, (n, a) in enumerate(self.calls)])
        return LLMResponse(content="Done.", usage={})


async def _turn(monkeypatch, log: _Log, script: _Script, executors: dict, **kwargs):
    for key, executor in executors.items():
        monkeypatch.setitem(tool_loop.EXECUTORS, key, executor)
    keys = sorted({name for name, _ in script.calls})

    async def tools():
        return [{"key": key, "description": key} for key in keys]
    return await tool_loop.run_native(system="S", user_content="question", history=[], resolve_tools=tools,
                                      emit=log.frames.append, on_chunk=lambda _: None, adapter_override=script,
                                      **kwargs)


def _steps(log: _Log) -> list[tuple[str, str]]:
    return [(f["type"], f["tool"]) for f in log.frames if f.get("type") in ("tool_call", "tool_result")]


async def test_two_reads_in_a_row_run_at_the_same_time(monkeypatch, execution_db):
    log = _Log()
    read = _Read(log, meet=2)
    result = await _turn(monkeypatch, log, _Script(("read_file", {"path": "a.md"}), ("list_dir", {"path": "b"})),
                         {"read_file": read, "list_dir": read})
    assert [s["result"].get("ok") for s in result["tool_trace"]] == [True, True]     # neither ran alone
    assert log.most == 2


async def test_at_most_four_run_at_once(monkeypatch, execution_db):
    log = _Log()
    gate = asyncio.Event()

    seen_while_held: list[int] = []
    gated: list[str] = []

    async def budget(tool_key, *, conversation_id):
        gated.append(tool_key)
        return None
    monkeypatch.setattr(tool_loop, "_check_fetch_budget", budget)

    async def watch():
        while len(gated) < 6:
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.05)        # every call has passed its gates: only the cap holds the last two
        seen_while_held.append(log.running)
        gate.set()

    class Waits(_Read):
        async def execute(self, args):
            log.events.append(("start", args["path"]))
            log.running += 1
            log.most = max(log.most, log.running)
            try:
                await asyncio.wait_for(gate.wait(), timeout=5)
            finally:
                log.running -= 1
            return {"ok": True, "text": args["path"]}

    watcher = asyncio.create_task(watch())
    reads = [("read_file", {"path": f"f{i}"}) for i in range(6)]
    result = await _turn(monkeypatch, log, _Script(*reads), {"read_file": Waits(log)})
    await watcher
    assert seen_while_held == [4] and log.most == 4
    assert [s["args"]["path"] for s in result["tool_trace"]] == [f"f{i}" for i in range(6)]


async def test_a_call_that_is_not_a_read_runs_alone_in_its_place(monkeypatch, execution_db):
    log = _Log()
    read, other = _Read(log, delay=0.05), _Read(log, delay=0.05)
    calls = [("read_file", {"path": "a"}), ("fixture_write", {"tag": "w"}), ("read_file", {"path": "b"}),
             ("list_dir", {"path": "c"})]
    result = await _turn(monkeypatch, log, _Script(*calls),
                         {"read_file": read, "list_dir": read, "fixture_write": other})
    order = log.events
    assert order.index(("end", "a")) < order.index(("start", "w")) < order.index(("end", "w"))
    assert order.index(("end", "w")) < min(order.index(("start", "b")), order.index(("start", "c")))
    assert order.index(("start", "c")) < order.index(("end", "b"))                   # b and c overlap
    assert [s["tool"] for s in result["tool_trace"]] == ["read_file", "fixture_write", "read_file", "list_dir"]


@pytest.mark.parametrize("middle", ["fixture_write", "render_chart", "update_plan"])
async def test_a_call_off_the_list_between_reads_keeps_everything_one_at_a_time(monkeypatch, execution_db, middle):
    log = _Log()
    read = _Read(log, delay=0.03)
    calls = [("read_file", {"path": "a"}), (middle, {"tag": "m"}), ("list_dir", {"path": "b"})]
    await _turn(monkeypatch, log, _Script(*calls), {"read_file": read, "list_dir": read, middle: _Read(log)})
    assert log.most == 1


async def test_frames_trace_and_history_keep_the_replys_order_whatever_finished_first(monkeypatch, execution_db):
    log = _Log()
    slow, fast = _Read(log, delay=0.3), _Read(log, delay=0.0)
    script = _Script(("read_file", {"path": "slow"}), ("list_dir", {"path": "fast"}))
    result = await _turn(monkeypatch, log, script, {"read_file": slow, "list_dir": fast})
    assert log.events.index(("end", "fast")) < log.events.index(("end", "slow"))       # fast finished first
    assert _steps(log) == [("tool_call", "read_file"), ("tool_result", "read_file"),     # each call next to
                           ("tool_call", "list_dir"), ("tool_result", "list_dir")]      # its own result
    assert [s["args"]["path"] for s in result["tool_trace"]] == ["slow", "fast"]
    sent = [str(m.get("content")) for m in script.requests[1]][1:]          # each call, then its own result
    assert ["invocation completed: read_file" in sent[0], "TOOL RESULT for read_file" in sent[1],
            "result of slow" in sent[1], "invocation completed: list_dir" in sent[2],
            "TOOL RESULT for list_dir" in sent[3], "result of fast" in sent[3]] == [True] * 6


async def test_a_refused_fetch_budget_lands_on_the_same_call(monkeypatch, execution_db):
    log = _Log()
    read = _Read(log)
    asked: list[str] = []

    async def budget(tool_key, *, conversation_id):
        asked.append(tool_key)
        if len(asked) == 2:
            return {"ok": False, "code": "fetch_budget", "error": "fetch budget used up"}
        return None
    monkeypatch.setattr(tool_loop, "_check_fetch_budget", budget)
    calls = [("read_file", {"path": "a"}), ("list_dir", {"path": "b"}), ("read_file", {"path": "c"})]
    result = await _turn(monkeypatch, log, _Script(*calls),
                         {"read_file": read, "list_dir": read})
    assert asked == ["read_file", "list_dir", "read_file"]
    assert [s["result"].get("code") for s in result["tool_trace"]] == [None, "fetch_budget", None]
    assert ("start", "b") not in log.events


async def test_the_turns_tool_limit_still_stops_the_call_past_it(monkeypatch, execution_db):
    log = _Log()
    read = _Read(log)
    calls = [("read_file", {"path": "a"}), ("list_dir", {"path": "b"}), ("read_file", {"path": "c"})]
    with execution_budget.scope(execution_budget.Budget(execution_budget.Limits(tool_calls=2))):
        result = await _turn(monkeypatch, log, _Script(*calls), {"read_file": read, "list_dir": read})
    assert [s["result"].get("code") for s in result["tool_trace"]] == [None, None, "task_budget_exhausted"]
    assert ("start", "c") not in log.events


@pytest.fixture
async def two_servers(execution_db):
    async with execution_db() as db:
        for sid in (7, 8):
            db.add(MCPServer(id=sid, label=f"s{sid}", command="x", args=[], env=None, status="connected",
                             state="ready", host_allowed=True))
            db.add(Toolset(key=f"mcp_{sid}", name=f"s{sid}", description="d", tier="orchestrator",
                           status="registered"))
        await db.flush()
        for key, hints in (("mcp_7__look", {"readOnlyHint": True}), ("mcp_7__find", {"readOnlyHint": True}),
                           ("mcp_8__look", {"readOnlyHint": True}), ("mcp_8__change", None),
                           ("mcp_8__wipe", {"readOnlyHint": True, "destructiveHint": True})):
            db.add(Tool(key=key, toolset_key=key.split("__")[0], tier="orchestrator", status="wired",
                        external_name=key.split("__")[1], input_schema={}, description=key, annotations=hints))
        await db.commit()
    return execution_db


async def test_reads_on_two_servers_overlap(monkeypatch, two_servers):
    log = _Log()
    read = _Read(log, meet=2)
    result = await _turn(monkeypatch, log, _Script(("mcp_7__look", {"tag": "x"}), ("mcp_8__look", {"tag": "y"})),
                         {"mcp_7__look": read, "mcp_8__look": read})
    assert [s["result"].get("ok") for s in result["tool_trace"]] == [True, True] and log.most == 2


@pytest.mark.parametrize("second", ["mcp_7__find", "mcp_8__change", "mcp_8__wipe"],
                         ids=["same-server", "not-read-only", "destructive"])
async def test_one_server_twice_or_a_tool_that_may_change_things_runs_alone(monkeypatch, two_servers, second):
    log = _Log()
    read = _Read(log, delay=0.03)
    await _turn(monkeypatch, log, _Script(("mcp_7__look", {"tag": "x"}), (second, {"tag": "y"})),
                {"mcp_7__look": read, second: read})
    assert log.most == 1


async def test_tools_serial_runs_one_at_a_time_again(monkeypatch, execution_db):
    async with execution_db() as db:
        db.add(Setting(key="tools_serial", value="true"))
        await db.commit()
    log = _Log()
    read = _Read(log, delay=0.03)
    await _turn(monkeypatch, log, _Script(("read_file", {"path": "a"}), ("list_dir", {"path": "b"})),
                {"read_file": read, "list_dir": read})
    assert log.most == 1


async def test_stopping_the_turn_stops_every_call_of_the_group(monkeypatch, execution_db):
    log = _Log()
    read = _Read(log, forever=True)
    turn = asyncio.create_task(_turn(monkeypatch, log, _Script(("read_file", {"path": "a"}),
                                                               ("list_dir", {"path": "b"})),
                                     {"read_file": read, "list_dir": read}))
    for _ in range(500):
        if log.running == 2:
            break
        await asyncio.sleep(0.01)
    assert log.running == 2
    stopped_at = asyncio.get_running_loop().time()
    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn
    assert sorted(read.cancelled) == ["a", "b"] and log.running == 0
    assert asyncio.get_running_loop().time() - stopped_at < tool_loop.TOOL_TIMEOUT_S / 4   # at once, not by timeout


async def test_a_read_that_already_ran_is_recorded_even_if_the_loop_stops_for_no_progress(monkeypatch, execution_db):
    """The same failing call three times stops the loop (K4a) after the third. The read after them already ran
    next to them: its result is recorded, not refused as task_no_progress (it would have been, one at a time)."""
    log = _Log()

    class Fails(_Read):
        async def execute(self, args):
            await super().execute(args)
            return {"ok": False, "error": "no such file"}
    read = _Read(log)
    calls = [("read_file", {"path": "x"})] * 3 + [("list_dir", {"path": "b"})]
    result = await _turn(monkeypatch, log, _Script(*calls), {"read_file": Fails(log), "list_dir": read})
    assert [s["result"].get("ok") for s in result["tool_trace"]] == [False, False, False, True]
    assert log.events.count(("start", "b")) == 1


def test_the_allowlist_is_reads_only():
    """Q2: never anything that shares one state (browser_*, desktop_*), plans, charts or delegates."""
    assert parallel_reads.READS == {"web_search", "web_extract", "read_skill", "recall", "read_file", "list_dir",
                                    "search_files", "list_my_tasks", "list_nodes", "list_my_capabilities",
                                    "whats_new", "task_progress", "background_status", "mac_list_shortcuts"}


async def test_the_run_record_has_one_step_per_call_with_its_own_arguments(monkeypatch, execution_db):
    """Review B1 on #368: RunRecorder pairs a tool_call with the next tool_result, and the run trace by position."""
    from datetime import datetime

    from server.orchestrator import run_trace
    from server.services.run_recorder import RunRecorder
    log = _Log()
    read = _Read(log, delay=0.02)
    calls = [("read_file", {"path": "A"}), ("list_dir", {"path": "B"}), ("read_file", {"path": "C"}),
             ("fixture_write", {"tag": "W"})]
    recorder = RunRecorder(run_id=1, started_at=datetime(2026, 10, 22), route_ms=None)
    with run_trace.collecting():
        for key, executor in {"read_file": read, "list_dir": read, "fixture_write": _Read(log)}.items():
            monkeypatch.setitem(tool_loop.EXECUTORS, key, executor)

        async def tools():
            return [{"key": key, "description": key} for key in ("read_file", "list_dir", "fixture_write")]
        await tool_loop.run_native(system="S", user_content="q", history=[], resolve_tools=tools,
                                   emit=recorder.tee(log.frames.append), on_chunk=lambda _: None,
                                   adapter_override=_Script(*calls))
        steps = [s for s in recorder._derive_steps("Done.") if s["kind"] == "tool_call"]
        recorder._merge_tool_trace(steps)
    assert log.most >= 2                                                        # A, B and C ran together
    assert [s["ref"]["tool"] for s in steps] == ["read_file", "list_dir", "read_file", "fixture_write"]
    for step, (_name, args) in zip(steps, calls):
        assert json.loads(step["detail"]["args_summary"]) == args
        assert json.loads(step["detail"]["args_full"]) == args


async def test_a_stop_while_a_later_call_is_in_its_gates_leaves_no_task_behind(monkeypatch, execution_db):
    """Review F2 on #368."""
    log = _Log()
    held = asyncio.Event()
    gated: list[str] = []

    async def budget(tool_key, *, conversation_id):
        gated.append(tool_key)
        if len(gated) == 2:
            await held.wait()                       # the second call never gets through its gates
        return None
    monkeypatch.setattr(tool_loop, "_check_fetch_budget", budget)
    before = set(asyncio.all_tasks())
    turn = asyncio.create_task(_turn(monkeypatch, log, _Script(("read_file", {"path": "a"}),
                                                               ("list_dir", {"path": "b"})),
                                     {"read_file": _Read(log, forever=True), "list_dir": _Read(log)}))
    for _ in range(500):
        if len(gated) == 2 and log.running == 1:
            break
        await asyncio.sleep(0.01)
    assert len(gated) == 2 and log.running == 1
    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn
    for _ in range(5):
        await asyncio.sleep(0)
    left = [t for t in asyncio.all_tasks() - before if t is not asyncio.current_task() and not t.done()]
    assert left == []


async def test_each_calls_gates_finish_before_the_next_calls_start(monkeypatch, execution_db):
    """Review F3 (a) on #368: the gates run one call after another, even when the first is slow."""
    log = _Log()
    gates: list[tuple[str, str]] = []

    async def budget(tool_key, *, conversation_id):
        gates.append(("start", tool_key))
        if tool_key == "read_file":
            await asyncio.sleep(0.1)
        gates.append(("end", tool_key))
        return None
    monkeypatch.setattr(tool_loop, "_check_fetch_budget", budget)
    read = _Read(log, meet=2)
    await _turn(monkeypatch, log, _Script(("read_file", {"path": "a"}), ("list_dir", {"path": "b"})),
                {"read_file": read, "list_dir": read})
    assert gates == [("start", "read_file"), ("end", "read_file"), ("start", "list_dir"), ("end", "list_dir")]
    assert log.most == 2


async def test_the_tool_limit_counts_a_call_the_cap_still_holds(monkeypatch, execution_db):
    """Review F3 (b) on #368: six reads, a limit of five, the cap holding the fifth when the sixth comes up."""
    log = _Log()
    read = _Read(log, delay=0.2)
    calls = [("read_file", {"path": f"f{i}"}) for i in range(6)]
    with execution_budget.scope(execution_budget.Budget(execution_budget.Limits(tool_calls=5))):
        result = await _turn(monkeypatch, log, _Script(*calls), {"read_file": read})
    assert [s["result"].get("code") for s in result["tool_trace"]] == [None] * 5 + ["task_budget_exhausted"]
    assert log.most == 4
