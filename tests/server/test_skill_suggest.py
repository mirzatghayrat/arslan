from arslan.models import LLMResponse
from server.services import skill_suggest


def _adapter(content):
    class _A:
        async def chat(self, system, user): return LLMResponse(content=content, usage={})
    return _A()


async def test_generate_ok(monkeypatch):
    body = "## Trigger\nwhen X\n## 决策规则\n- do Y"
    import json as _j
    payload = _j.dumps({"name": "Repo Technique", "category": "research",
                        "description": "A technique distilled from the repo.", "body": body})
    async def fake(role=None): return _adapter(payload)
    monkeypatch.setattr(skill_suggest, "build_adapter", fake)
    r = await skill_suggest.generate_skill({"full_name": "o/r", "description": "", "topics": []}, "readme")
    assert r is not None and r["name"] == "Repo Technique"
    assert "## Trigger" in r["body"] and "## 决策规则" in r["body"]


async def test_generate_missing_sections_none(monkeypatch):
    import json as _j
    payload = _j.dumps({"name": "X", "category": "c", "description": "d", "body": "just prose, no sections"})
    async def fake(role=None): return _adapter(payload)
    monkeypatch.setattr(skill_suggest, "build_adapter", fake)
    assert await skill_suggest.generate_skill({"full_name": "o/r"}, "readme") is None


async def test_generate_conservative_on_error(monkeypatch):
    async def fake(role=None):
        class _A:
            async def chat(self, system, user): raise RuntimeError("down")
        return _A()
    monkeypatch.setattr(skill_suggest, "build_adapter", fake)
    assert await skill_suggest.generate_skill({"full_name": "o/r"}, "readme") is None


async def test_generate_unparseable_none(monkeypatch):
    async def fake(role=None): return _adapter("not json")
    monkeypatch.setattr(skill_suggest, "build_adapter", fake)
    assert await skill_suggest.generate_skill({"full_name": "o/r"}, "readme") is None
