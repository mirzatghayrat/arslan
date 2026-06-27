from arslan.models import LLMResponse
from server.services import mcp_suggest


def _adapter(content):
    class _A:
        async def chat(self, system, user): return LLMResponse(content=content, usage={})
    return _A()


async def test_suggest_stdio(monkeypatch):
    async def fake(role=None): return _adapter(
        '{"is_mcp": true, "transport": "stdio", "command": "npx", "args": ["-y", "@scope/srv"], "url": null, "reason": "README shows npx run"}')
    monkeypatch.setattr(mcp_suggest, "build_adapter", fake)
    r = await mcp_suggest.classify_and_suggest({"full_name": "a/b", "description": "", "topics": []}, "README npx -y @scope/srv")
    assert r["is_mcp"] is True and r["transport"] == "stdio"
    assert r["command"] == "npx" and r["args"] == ["-y", "@scope/srv"]


async def test_suggest_http(monkeypatch):
    async def fake(role=None): return _adapter(
        '{"is_mcp": true, "transport": "http", "command": null, "args": [], "url": "https://x/mcp", "reason": "hosted"}')
    monkeypatch.setattr(mcp_suggest, "build_adapter", fake)
    r = await mcp_suggest.classify_and_suggest({"full_name": "a/b"}, "hosted at https://x/mcp")
    assert r["is_mcp"] is True and r["transport"] == "http" and r["url"] == "https://x/mcp"


async def test_suggest_not_mcp(monkeypatch):
    async def fake(role=None): return _adapter('{"is_mcp": false, "reason": "just a library"}')
    monkeypatch.setattr(mcp_suggest, "build_adapter", fake)
    r = await mcp_suggest.classify_and_suggest({"full_name": "a/b"}, "a python lib")
    assert r["is_mcp"] is False and r["transport"] is None


async def test_suggest_conservative_on_error(monkeypatch):
    async def fake(role=None):
        class _A:
            async def chat(self, system, user): raise RuntimeError("llm down")
        return _A()
    monkeypatch.setattr(mcp_suggest, "build_adapter", fake)
    r = await mcp_suggest.classify_and_suggest({"full_name": "a/b"}, "x")
    assert r["is_mcp"] is False


async def test_suggest_bad_transport_rejected(monkeypatch):
    async def fake(role=None): return _adapter('{"is_mcp": true, "transport": "carrier_pigeon", "command": "x"}')
    monkeypatch.setattr(mcp_suggest, "build_adapter", fake)
    r = await mcp_suggest.classify_and_suggest({"full_name": "a/b"}, "x")
    assert r["is_mcp"] is False     # unknown transport → not usable → conservative
