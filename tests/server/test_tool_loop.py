import pytest
from server.orchestrator import tool_loop


class _Resp:
    def __init__(self, content): self.content = content


class _ScriptedAdapter:
    """Returns queued responses; records the systems/users it saw."""
    def __init__(self, replies): self._replies = list(replies); self.calls = []
    async def chat(self, system, user, history=None):
        self.calls.append({"system": system, "user": user, "history": history})
        return _Resp(self._replies.pop(0))


def _tools(*keys):
    async def _r(): return [{"key": k, "description": f"{k} desc"} for k in keys]
    return _r


async def test_plain_final_answer(monkeypatch):
    adapter = _ScriptedAdapter(["just an answer"])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    chunks = []
    out = await tool_loop.run(system="S", user_content="hi", history=[],
                              emit=lambda e: None, on_chunk=chunks.append,
                              resolve_tools=_tools())
    assert out["final"] == "just an answer"
    assert out["escalation"] is None
    assert "".join(chunks) == "just an answer"


async def test_tool_call_executes_and_feeds_back(monkeypatch):
    from server.registry import executors
    adapter = _ScriptedAdapter(['{"tool": "web_search", "args": {"query": "x"}}', "final after tool"])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    class _Stub:
        async def execute(self, args): return {"ok": True, "results": [{"title": "t"}]}
    monkeypatch.setitem(executors.EXECUTORS, "web_search", _Stub())
    events = []
    out = await tool_loop.run(system="S", user_content="search x", history=[],
                              emit=events.append, on_chunk=lambda c: None,
                              resolve_tools=_tools("web_search"))
    assert out["final"] == "final after tool"
    assert out["tool_trace"][0]["tool"] == "web_search"
    assert any(e["type"] == "tool_call" for e in events)
    assert any(e["type"] == "tool_result" and e["ok"] for e in events)
    assert "TOOL RESULT for web_search" in adapter.calls[1]["user"]


async def test_unavailable_tool_refused(monkeypatch):
    adapter = _ScriptedAdapter(['{"tool": "danger", "args": {}}', "fell back to answer"])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    out = await tool_loop.run(system="S", user_content="go", history=[],
                              emit=lambda e: None, on_chunk=lambda c: None,
                              resolve_tools=_tools("web_search"))
    assert out["final"] == "fell back to answer"
    assert out["tool_trace"][0]["result"]["ok"] is False


async def test_escalation_disabled_continues(monkeypatch):
    adapter = _ScriptedAdapter(['{"escalate": {"kind": "data", "need": "X", "context": "Y"}}', "answered anyway"])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    out = await tool_loop.run(system="S", user_content="go", history=[],
                              emit=lambda e: None, on_chunk=lambda c: None,
                              resolve_tools=_tools("web_search"), allow_escalation=False)
    assert out["escalation"] is None
    assert out["final"] == "answered anyway"


async def test_escalation_enabled_returns(monkeypatch):
    adapter = _ScriptedAdapter(['{"escalate": {"kind": "capability", "need": "N", "context": "C"}}'])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    out = await tool_loop.run(system="S", user_content="go", history=[],
                              emit=lambda e: None, on_chunk=lambda c: None,
                              resolve_tools=_tools("web_search"), allow_escalation=True)
    assert out["final"] is None
    assert out["escalation"]["need"] == "N"
