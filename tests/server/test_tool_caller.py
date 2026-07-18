"""Tests for the ToolCaller contextvar (server.orchestrator.tool_caller) and its threading
through tool_loop._dispatch_tool / run_native.

Why this exists (brain-P2 Task 1): executors currently get only `execute(args)` — no identity
of WHO is calling (host answer path vs. a spawn's mini agent-loop). The upcoming memory-write
executor must know the caller to enforce scope isolation, and must FAIL CLOSED (refuse to
write) when no caller is set rather than guessing. This contextvar is the plumbing for that:
set immediately before `executor.execute(args)`, reset in `finally` (zero residual pollution
across turns/dispatches), and threaded from the two production run_native entry points
(arslan.py's host answer path, spawn_loop.py's spawn loop).
"""
from __future__ import annotations

import pytest

from server.orchestrator import tool_caller
from server.orchestrator.tool_caller import ToolCaller


# ---------------------------------------------------------------------------
# Unit-level: the contextvar itself
# ---------------------------------------------------------------------------

def test_current_caller_defaults_to_none():
    assert tool_caller.current_caller() is None


def test_set_then_read_then_reset():
    caller = ToolCaller(actor="host", spawn_id=None, conversation_id="c1")
    token = tool_caller.set_caller(caller)
    try:
        assert tool_caller.current_caller() == caller
    finally:
        tool_caller.reset_caller(token)
    assert tool_caller.current_caller() is None


def test_residual_free_across_two_sequential_dispatches():
    """Simulates two sequential tool dispatches sharing the same (test) context: set A /
    finally-reset, then set B / finally-reset. The read immediately BEFORE the second set
    must be None — no cross-turn leak of dispatch A's caller into dispatch B."""
    caller_a = ToolCaller(actor="host", spawn_id=None, conversation_id="c1")
    caller_b = ToolCaller(actor="spawn", spawn_id=42, conversation_id="c2")

    token_a = tool_caller.set_caller(caller_a)
    try:
        assert tool_caller.current_caller() == caller_a
    finally:
        tool_caller.reset_caller(token_a)

    # THE residual check: nothing leaks from dispatch A into the gap before dispatch B.
    assert tool_caller.current_caller() is None

    token_b = tool_caller.set_caller(caller_b)
    try:
        assert tool_caller.current_caller() == caller_b
    finally:
        tool_caller.reset_caller(token_b)

    assert tool_caller.current_caller() is None


def test_exception_during_set_scope_still_resets():
    """If the code inside the set/reset scope raises, the finally must still reset — this is
    the exact shape _dispatch_tool uses around executor.execute (which can raise)."""
    caller = ToolCaller(actor="host", spawn_id=None, conversation_id="c1")
    token = tool_caller.set_caller(caller)
    with pytest.raises(RuntimeError):
        try:
            assert tool_caller.current_caller() == caller
            raise RuntimeError("executor blew up")
        finally:
            tool_caller.reset_caller(token)
    assert tool_caller.current_caller() is None


def test_fail_closed_seed_stub_executor_refuses_when_caller_none():
    """Proves the None-refusal pattern the memory-write executor (Task 4) will rely on: a stub
    executor that checks current_caller() and refuses when it is None."""

    class _FailClosedStub:
        async def execute(self, args):
            if tool_caller.current_caller() is None:
                return {"ok": False, "error": "no caller identity — refusing write"}
            return {"ok": True}

    import asyncio

    stub = _FailClosedStub()

    # No caller set at all → refuse.
    result = asyncio.run(stub.execute({}))
    assert result == {"ok": False, "error": "no caller identity — refusing write"}

    # Caller set → allowed.
    async def _with_caller():
        token = tool_caller.set_caller(ToolCaller("host", None, "c1"))
        try:
            return await stub.execute({})
        finally:
            tool_caller.reset_caller(token)

    result2 = asyncio.run(_with_caller())
    assert result2 == {"ok": True}


# ---------------------------------------------------------------------------
# Threading: _dispatch_tool sets/resets around executor.execute
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_tool_threads_caller_to_executor_and_resets_after():
    from server.orchestrator import tool_loop
    from server.registry import executors

    seen = {}

    class _Stub:
        async def execute(self, args):
            seen["during"] = tool_caller.current_caller()
            return {"ok": True}

    monkey_key = "web_search"
    orig = executors.EXECUTORS.get(monkey_key)
    executors.EXECUTORS[monkey_key] = _Stub()
    try:
        async def _resolve():
            return [{"key": monkey_key, "description": "d"}]

        caller = ToolCaller(actor="spawn", spawn_id=7, conversation_id="c9")
        assert tool_caller.current_caller() is None  # sanity: nothing leaked in from another test

        result = await tool_loop._dispatch_tool(
            monkey_key, {"query": "x"}, "assistant content",
            resolve_tools=_resolve, emit=lambda e: None, tool_timeout_s=5.0,
            tool_trace=[], convo=[], caller=caller)

        assert result["ok"] is True
        assert seen["during"] == caller
        # finally ran: no residual after _dispatch_tool returns.
        assert tool_caller.current_caller() is None
    finally:
        if orig is not None:
            executors.EXECUTORS[monkey_key] = orig
        else:
            executors.EXECUTORS.pop(monkey_key, None)


@pytest.mark.asyncio
async def test_dispatch_tool_no_caller_passed_is_a_noop_context():
    """caller=None (default) must not set anything — current_caller() stays None throughout,
    matching today's behavior for any call site that hasn't been updated yet."""
    from server.orchestrator import tool_loop
    from server.registry import executors

    seen = {}

    class _Stub:
        async def execute(self, args):
            seen["during"] = tool_caller.current_caller()
            return {"ok": True}

    monkey_key = "web_search"
    orig = executors.EXECUTORS.get(monkey_key)
    executors.EXECUTORS[monkey_key] = _Stub()
    try:
        async def _resolve():
            return [{"key": monkey_key, "description": "d"}]

        result = await tool_loop._dispatch_tool(
            monkey_key, {"query": "x"}, "assistant content",
            resolve_tools=_resolve, emit=lambda e: None, tool_timeout_s=5.0,
            tool_trace=[], convo=[])  # no caller kwarg at all

        assert result["ok"] is True
        assert seen["during"] is None
        assert tool_caller.current_caller() is None
    finally:
        if orig is not None:
            executors.EXECUTORS[monkey_key] = orig
        else:
            executors.EXECUTORS.pop(monkey_key, None)


@pytest.mark.asyncio
async def test_dispatch_tool_resets_even_when_executor_raises():
    from server.orchestrator import tool_loop
    from server.registry import executors

    class _Boom:
        async def execute(self, args):
            assert tool_caller.current_caller() is not None
            raise ValueError("executor exploded")

    monkey_key = "web_search"
    orig = executors.EXECUTORS.get(monkey_key)
    executors.EXECUTORS[monkey_key] = _Boom()
    try:
        async def _resolve():
            return [{"key": monkey_key, "description": "d"}]

        caller = ToolCaller(actor="host", spawn_id=None, conversation_id="c1")
        result = await tool_loop._dispatch_tool(
            monkey_key, {"query": "x"}, "assistant content",
            resolve_tools=_resolve, emit=lambda e: None, tool_timeout_s=5.0,
            tool_trace=[], convo=[], caller=caller)

        # _dispatch_tool swallows the exception into an {ok: False} result (existing behavior)
        assert result["ok"] is False
        # but the caller contextvar must still have been reset in finally.
        assert tool_caller.current_caller() is None
    finally:
        if orig is not None:
            executors.EXECUTORS[monkey_key] = orig
        else:
            executors.EXECUTORS.pop(monkey_key, None)


# ---------------------------------------------------------------------------
# End-to-end: run_native threads caller into BOTH _dispatch_tool call sites
# (the force_tools pre-run path AND the model-driven tool-call loop).
# ---------------------------------------------------------------------------

class _LLMResp:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _NativeAdapter:
    def __init__(self, replies):
        self._r = list(replies)
        self.calls = []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        self.calls.append({"system": system, "user": user, "history": history, "tools": tools})
        return self._r.pop(0)


def _tc(name, args):
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": args}}


@pytest.mark.asyncio
async def test_run_native_threads_caller_through_model_driven_dispatch(monkeypatch):
    from server.orchestrator import tool_loop
    from server.registry import executors

    seen = []

    class _Stub:
        async def execute(self, args):
            seen.append(tool_caller.current_caller())
            return {"ok": True, "summary": "ok"}
    monkeypatch.setitem(executors.EXECUTORS, "web_search", _Stub())

    adapter = _NativeAdapter([
        _LLMResp(content="searching", tool_calls=[_tc("web_search", {"query": "x"})]),
        _LLMResp(content="final answer", tool_calls=[]),
    ])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    async def _resolve():
        return [{"key": "web_search", "description": "search"}]

    caller = ToolCaller(actor="host", spawn_id=None, conversation_id="c1")
    r = await tool_loop.run_native(
        system="s", user_content="search x", history=[], emit=lambda e: None,
        on_chunk=lambda c: None, resolve_tools=_resolve, caller=caller)

    assert r["final"] == "final answer"
    assert seen == [caller]
    # no residual after the whole run_native call returns.
    assert tool_caller.current_caller() is None


@pytest.mark.asyncio
async def test_run_native_threads_caller_through_force_tools_prerun_dispatch(monkeypatch):
    """Covers the OTHER _dispatch_tool call site inside run_native: the force_tools
    deterministic pre-run path (spawn_loop always passes force_tools=True)."""
    from server.orchestrator import tool_loop
    from server.registry import executors
    from server.services import tool_intent

    seen = []

    class _Stub:
        async def execute(self, args):
            seen.append(tool_caller.current_caller())
            return {"ok": True, "summary": "ok"}
    monkeypatch.setitem(executors.EXECUTORS, "web_search", _Stub())

    class _Intent:
        needs = True
        tool = "web_search"
        query = "forced query"

    async def _classify(*a, **kw):
        return _Intent()
    monkeypatch.setattr(tool_intent, "classify", _classify)

    adapter = _NativeAdapter([_LLMResp(content="final answer", tool_calls=[])])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    async def _resolve():
        return [{"key": "web_search", "description": "search"}]

    caller = ToolCaller(actor="spawn", spawn_id=3, conversation_id="c2")
    r = await tool_loop.run_native(
        system="s", user_content="do the thing", history=[], emit=lambda e: None,
        on_chunk=lambda c: None, resolve_tools=_resolve, force_tools=True, caller=caller)

    assert r["final"] == "final answer"
    assert seen == [caller]
    assert tool_caller.current_caller() is None
