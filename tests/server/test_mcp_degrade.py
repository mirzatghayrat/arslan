"""PB-3: turn-scoped MCP consecutive-failure degrade hint.

When an `mcp_*` tool fails ≥2 times consecutively in ONE run_native invocation, the
recorded tool-result message gains a deterministic hint steering the model to the
equivalent builtin (web_extract / web_search). The hint is trusted framing — it sits
OUTSIDE the wrap_external data frame. 条件2: the counter lives in run_native locals,
so a fresh invocation (new turn) starts at zero, and a success resets the streak.
条件4: the KEY test drives the full chain — the scripted model actually SWITCHES to
web_extract after seeing the hint, and succeeds.
"""
import pytest

from server.orchestrator import tool_loop
from server.orchestrator.untrusted import DELIM_CLOSE


class _LLMResp:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _ScriptedAdapter:
    """Queued LLMResponses, one per chat() call; records every call's inputs."""

    def __init__(self, replies):
        self._r = list(replies)
        self.calls = []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        self.calls.append({"system": system, "user": user, "history": history,
                           "tools": tools})
        return self._r.pop(0)


def _tc(name, args):
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": args}}


async def _resolve():
    return [{"key": "mcp_4__fetch", "description": "MCP fetch a URL"},
            {"key": "web_extract", "description": "builtin page extract"}]


class _FailingExec:
    """Always fails — plays the broken mcp-server-fetch."""

    def __init__(self):
        self.n = 0

    async def execute(self, args):
        self.n += 1
        return {"ok": False, "error": "MCP tool call failed: Failed to fetch"}


class _OkExtract:
    def __init__(self):
        self.n = 0

    async def execute(self, args):
        self.n += 1
        return {"ok": True, "text": "raw.githubusercontent page content " * 20}


class _ScriptedExec:
    """Returns queued results (fail/ok per call) — for the mid-turn reset test."""

    def __init__(self, results):
        self._r = list(results)

    async def execute(self, args):
        return self._r.pop(0)


def _wire(monkeypatch, executors: dict):
    async def fake_resolve(key):
        return executors.get(key)
    monkeypatch.setattr(tool_loop, "resolve_executor", fake_resolve)


def _capture_events(monkeypatch):
    from server.services import recap_service
    events = []

    async def fake_log(conversation_id, kind, ref, summary):
        events.append({"conversation_id": conversation_id, "kind": kind,
                       "ref": ref, "summary": summary})
    monkeypatch.setattr(recap_service, "log_event", fake_log)
    return events


def _convo_blob(call: dict) -> str:
    return str(call["user"]) + str(call["history"])


HINT_MARK = "已连续失败"


@pytest.mark.asyncio
async def test_full_chain_hint_makes_model_switch_to_builtin(monkeypatch):
    # 条件4 KEY test: fail → fail (hint fires) → model switches to web_extract → final.
    fetch, extract = _FailingExec(), _OkExtract()
    _wire(monkeypatch, {"mcp_4__fetch": fetch, "web_extract": extract})
    events = _capture_events(monkeypatch)
    adapter = _ScriptedAdapter([
        _LLMResp(content="", tool_calls=[_tc("mcp_4__fetch", {"url": "https://raw.githubusercontent.com/x"})]),
        _LLMResp(content="", tool_calls=[_tc("mcp_4__fetch", {"url": "https://raw.githubusercontent.com/x"})]),
        _LLMResp(content="", tool_calls=[_tc("web_extract", {"url": "https://raw.githubusercontent.com/x"})]),
        _LLMResp(content="拿到内容了,答案如下。", tool_calls=[]),
    ])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    r = await tool_loop.run_native(
        system="s", user_content="抓取 raw.githubusercontent 上的 README", history=[],
        emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=_resolve,
        conversation_id="conv-pb3")

    # (c) call#2 saw ONLY the first failure — no hint yet.
    assert HINT_MARK not in _convo_blob(adapter.calls[1])
    # (a) call#3 saw the second failure WITH the deterministic hint, naming web_extract.
    blob3 = _convo_blob(adapter.calls[2])
    assert "此 MCP 工具本回合已连续失败 2 次" in blob3
    assert "web_extract" in blob3
    assert "不要再重试该 MCP 工具" in blob3
    # The hint is OUR trusted framing: it sits AFTER the external-data close marker,
    # never inside the wrapped (untrusted) region.
    msgs = [str(m.get("content", "")) for m in (adapter.calls[2]["history"] or [])]
    msgs.append(str(adapter.calls[2]["user"]))   # the hinted TOOL RESULT is the latest turn
    failed_msg = next(m for m in msgs if HINT_MARK in m)
    assert failed_msg.index(DELIM_CLOSE) < failed_msg.index(HINT_MARK)
    # (b) the model actually switched: web_extract ran ONCE, succeeded, then call#4 answered.
    assert extract.n == 1
    assert fetch.n == 2
    assert len(adapter.calls) == 4
    assert r["final"] == "拿到内容了,答案如下。"
    trace = r["tool_trace"]
    assert trace[-1]["tool"] == "web_extract" and trace[-1]["result"]["ok"]
    # observability: exactly ONE mcp_degrade_hint event, first time the hint fired.
    hint_events = [e for e in events if e["kind"] == "mcp_degrade_hint"]
    assert len(hint_events) == 1
    assert hint_events[0]["conversation_id"] == "conv-pb3"
    assert hint_events[0]["ref"] == {"tool_key": "mcp_4__fetch", "count": 2}


@pytest.mark.asyncio
async def test_third_failure_hints_again_but_logs_once(monkeypatch):
    fetch = _FailingExec()
    _wire(monkeypatch, {"mcp_4__fetch": fetch, "web_extract": _OkExtract()})
    events = _capture_events(monkeypatch)
    adapter = _ScriptedAdapter([
        _LLMResp(content="", tool_calls=[_tc("mcp_4__fetch", {"url": "u"})]),
        _LLMResp(content="", tool_calls=[_tc("mcp_4__fetch", {"url": "u"})]),
        _LLMResp(content="", tool_calls=[_tc("mcp_4__fetch", {"url": "u"})]),   # stubborn retry
        _LLMResp(content="放弃,直接回答。", tool_calls=[]),
    ])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    await tool_loop.run_native(
        system="s", user_content="fetch u", history=[], emit=lambda e: None,
        on_chunk=lambda c: None, resolve_tools=_resolve, conversation_id="conv-x")
    # hint escalates its count on the 3rd consecutive failure…
    assert "已连续失败 3 次" in _convo_blob(adapter.calls[3])
    # …but the conversation_events row is logged only ONCE per turn per tool.
    assert len([e for e in events if e["kind"] == "mcp_degrade_hint"]) == 1


@pytest.mark.asyncio
async def test_fresh_invocation_starts_at_zero(monkeypatch):
    # 条件2: turn A ends with the tool at 2 consecutive failures; turn B is a NEW
    # run_native invocation — its first failure must NOT carry a hint.
    _wire(monkeypatch, {"mcp_4__fetch": _FailingExec(), "web_extract": _OkExtract()})
    _capture_events(monkeypatch)

    adapter_a = _ScriptedAdapter([
        _LLMResp(content="", tool_calls=[_tc("mcp_4__fetch", {"url": "u"})]),
        _LLMResp(content="", tool_calls=[_tc("mcp_4__fetch", {"url": "u"})]),
        _LLMResp(content="turn A done", tool_calls=[]),
    ])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter_a)
    await tool_loop.run_native(
        system="s", user_content="turn A", history=[], emit=lambda e: None,
        on_chunk=lambda c: None, resolve_tools=_resolve)
    assert "已连续失败 2 次" in _convo_blob(adapter_a.calls[2])  # turn A did hint

    adapter_b = _ScriptedAdapter([
        _LLMResp(content="", tool_calls=[_tc("mcp_4__fetch", {"url": "u"})]),
        _LLMResp(content="turn B done", tool_calls=[]),
    ])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter_b)
    await tool_loop.run_native(
        system="s", user_content="turn B", history=[], emit=lambda e: None,
        on_chunk=lambda c: None, resolve_tools=_resolve)
    # turn B's FIRST failure: count restarted at 1 → no hint anywhere.
    assert all(HINT_MARK not in _convo_blob(c) for c in adapter_b.calls)


@pytest.mark.asyncio
async def test_success_resets_counter_mid_turn(monkeypatch):
    # fail → success → fail: the success resets the streak, so the second failure
    # is count 1 again — no hint.
    scripted = _ScriptedExec([
        {"ok": False, "error": "Failed to fetch"},
        {"ok": True, "text": "got it this time"},
        {"ok": False, "error": "Failed to fetch"},
    ])
    _wire(monkeypatch, {"mcp_4__fetch": scripted, "web_extract": _OkExtract()})
    _capture_events(monkeypatch)
    adapter = _ScriptedAdapter([
        _LLMResp(content="", tool_calls=[_tc("mcp_4__fetch", {"url": "u1"})]),
        _LLMResp(content="", tool_calls=[_tc("mcp_4__fetch", {"url": "u2"})]),
        _LLMResp(content="", tool_calls=[_tc("mcp_4__fetch", {"url": "u3"})]),
        _LLMResp(content="done", tool_calls=[]),
    ])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    await tool_loop.run_native(
        system="s", user_content="go", history=[], emit=lambda e: None,
        on_chunk=lambda c: None, resolve_tools=_resolve)
    assert all(HINT_MARK not in _convo_blob(c) for c in adapter.calls)


@pytest.mark.asyncio
async def test_non_mcp_tool_failures_never_hint(monkeypatch):
    class _FailExtract:
        async def execute(self, args):
            return {"ok": False, "error": "timeout"}
    _wire(monkeypatch, {"web_extract": _FailExtract()})
    events = _capture_events(monkeypatch)
    adapter = _ScriptedAdapter([
        _LLMResp(content="", tool_calls=[_tc("web_extract", {"url": "u"})]),
        _LLMResp(content="", tool_calls=[_tc("web_extract", {"url": "u"})]),
        _LLMResp(content="", tool_calls=[_tc("web_extract", {"url": "u"})]),
        _LLMResp(content="answered without it", tool_calls=[]),
    ])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    r = await tool_loop.run_native(
        system="s", user_content="extract u", history=[], emit=lambda e: None,
        on_chunk=lambda c: None, resolve_tools=_resolve, conversation_id="conv-y")
    assert all(HINT_MARK not in _convo_blob(c) for c in adapter.calls)
    assert not events
    assert r["final"] == "answered without it"


@pytest.mark.asyncio
async def test_no_conversation_id_is_fail_open(monkeypatch):
    # Without a conversation_id the hint still fires; event logging no-ops harmlessly.
    _wire(monkeypatch, {"mcp_4__fetch": _FailingExec(), "web_extract": _OkExtract()})
    adapter = _ScriptedAdapter([
        _LLMResp(content="", tool_calls=[_tc("mcp_4__fetch", {"url": "u"})]),
        _LLMResp(content="", tool_calls=[_tc("mcp_4__fetch", {"url": "u"})]),
        _LLMResp(content="done", tool_calls=[]),
    ])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    r = await tool_loop.run_native(
        system="s", user_content="fetch u", history=[], emit=lambda e: None,
        on_chunk=lambda c: None, resolve_tools=_resolve)   # no conversation_id
    assert "已连续失败 2 次" in _convo_blob(adapter.calls[2])
    assert r["final"] == "done"
