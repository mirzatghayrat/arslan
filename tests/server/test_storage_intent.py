from arslan.models import LLMResponse
from server.services import storage_intent


def _adapter(content):
    class _A:
        async def chat(self, system, user):
            return LLMResponse(content=content, usage={})
    return _A()


async def test_store_intent_named_target(monkeypatch):
    async def fake_build(role=None): return _adapter('{"store": true, "target": "小美"}')
    monkeypatch.setattr(storage_intent, "build_adapter", fake_build)
    r = await storage_intent.classify("把这份资料存给小美", ["report.pdf"], ["小美", "股小助"])
    assert r.store is True
    assert r.target == "小美"


async def test_no_store_default(monkeypatch):
    async def fake_build(role=None): return _adapter('{"store": false, "target": null}')
    monkeypatch.setattr(storage_intent, "build_adapter", fake_build)
    r = await storage_intent.classify("总结一下这个", ["report.pdf"], ["小美"])
    assert r.store is False


async def test_store_no_target(monkeypatch):
    async def fake_build(role=None): return _adapter('{"store": true, "target": null}')
    monkeypatch.setattr(storage_intent, "build_adapter", fake_build)
    r = await storage_intent.classify("记住这份资料", ["report.pdf"], ["小美", "股小助"])
    assert r.store is True
    assert r.target is None


async def test_conservative_on_llm_error(monkeypatch):
    async def fake_build(role=None):
        class _A:
            async def chat(self, system, user): raise RuntimeError("llm down")
        return _A()
    monkeypatch.setattr(storage_intent, "build_adapter", fake_build)
    r = await storage_intent.classify("记住这份", ["x.pdf"], ["小美"])
    assert r.store is False   # uncertain → don't store


async def test_conservative_on_unparseable(monkeypatch):
    async def fake_build(role=None): return _adapter("not json at all")
    monkeypatch.setattr(storage_intent, "build_adapter", fake_build)
    r = await storage_intent.classify("记住这份", ["x.pdf"], ["小美"])
    assert r.store is False   # parse_json_object returns None → no-store
