import pytest
from arslan.models import LLMResponse
from server.services import tool_intent


def _adapter(content):
    class _A:
        async def chat(self, system, user):
            return LLMResponse(content=content, usage={})
    return _A()


async def test_needs_web_search_with_query(monkeypatch):
    async def fake_build(role=None): return _adapter('{"needs": true, "tool": "web_search", "query": "Tesla stock price this week"}')
    monkeypatch.setattr(tool_intent, "build_adapter", fake_build)
    r = await tool_intent.classify("查一下特斯拉近一周股价画折线图", ["web_search", "render_chart"])
    assert r.needs is True
    assert r.tool == "web_search"
    assert "Tesla" in r.query


async def test_no_tool_needed(monkeypatch):
    async def fake_build(role=None): return _adapter('{"needs": false, "tool": null, "query": null}')
    monkeypatch.setattr(tool_intent, "build_adapter", fake_build)
    r = await tool_intent.classify("讲个笑话", ["web_search"])
    assert r.needs is False
    assert r.tool is None


async def test_conservative_on_error(monkeypatch):
    async def fake_build(role=None):
        class _A:
            async def chat(self, system, user): raise RuntimeError("llm down")
        return _A()
    monkeypatch.setattr(tool_intent, "build_adapter", fake_build)
    r = await tool_intent.classify("anything", ["web_search"])
    assert r.needs is False and r.tool is None


async def test_conservative_on_unparseable(monkeypatch):
    async def fake_build(role=None): return _adapter("not json")
    monkeypatch.setattr(tool_intent, "build_adapter", fake_build)
    r = await tool_intent.classify("anything", ["web_search"])
    assert r.needs is False


async def test_tool_not_in_available_dropped(monkeypatch):
    async def fake_build(role=None): return _adapter('{"needs": true, "tool": "carrier_pigeon", "query": "x"}')
    monkeypatch.setattr(tool_intent, "build_adapter", fake_build)
    r = await tool_intent.classify("x", ["web_search"])   # carrier_pigeon not available
    assert r.tool is None      # unknown tool → dropped
    assert r.needs is False     # needs forced False when no usable tool resolved
