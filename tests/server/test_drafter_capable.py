import anyio
from server.services import spawn_drafter


def test_draft_is_capable(monkeypatch):
    # Stub the persona LLM draft.
    class Resp:
        content = ('{"name":"game-numeric","domain":"game-design.numerical",'
                   '"capabilities":["数值建模","平衡性分析"],"persona_role":"数值策划","persona_tone":"硬核"}')

    class A:
        async def chat(self, *, system, user):
            return Resp()

    monkeypatch.setattr(spawn_drafter, "_get_adapter", lambda: A())

    # Stub registry text + facts so no DB needed.
    async def fake_registry():
        return ""

    monkeypatch.setattr(spawn_drafter._router, "_spawn_registry", fake_registry)

    async def fake_facts():
        return ""

    monkeypatch.setattr(spawn_drafter.memory, "facts_text", fake_facts)

    # Stub seed search + curate.
    async def fake_search(q, k=3):
        return [{"slug": "game-economy-designer", "name": "Game Economy Designer"}]

    monkeypatch.setattr(spawn_drafter.persona_seed_service, "search", fake_search)

    async def fake_curate(need):
        return {"toolsets": ["web-search"], "skills": ["statistical-analysis"],
                "mcps": ["mcp_7"], "gaps": ["实时榜单数据"]}

    monkeypatch.setattr(spawn_drafter.equipment_service, "curate", fake_curate)

    d = anyio.run(lambda: spawn_drafter.draft_from_text("做个手游数值策划分身"))
    assert d["domain"] == "game-design.numerical"
    assert d["tools"] == ["web-search"]
    assert d["skills"] == ["statistical-analysis"]
    assert d["mcps"] == ["mcp_7"]
    assert d["gaps"] == ["实时榜单数据"]
    assert d["seed_refs"] == ["game-economy-designer"]
