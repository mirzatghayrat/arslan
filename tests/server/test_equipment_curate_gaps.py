"""curate() also returns validated MCP toolsets + capability gaps (T4).

REAL registry shape (verified against server/registry/service.py +
server/mcp/discovery.py + server/services/mcp_service.py):
  - There is NO separate "mcp" kind. An MCP server materializes as a
    Toolset whose key starts with "mcp_<server_id>". When the operator
    exposes it (mcp_service.set_exposed), that toolset flips to tier="safe"
    so it appears in safe_menu()["toolsets"] and passes
    assert_assignable("toolset", "mcp_<id>").
  - Therefore curate validates MCP picks via assert_assignable("toolset", key)
    and surfaces them under the additive out["mcps"] list. "gaps" passes
    through (needs the LLM flagged as having no menu match).
"""
from server.services import equipment_service


async def test_curate_returns_mcps_and_gaps(monkeypatch):
    async def fake_safe_menu():
        # MCP entries are toolsets with an mcp_ key; tier already flipped to safe.
        return {
            "toolsets": [
                {"key": "web_search_scraping", "name": "Web", "description": "search",
                 "tier": "safe", "status": "wired"},
                {"key": "mcp_7", "name": "GitHub MCP", "description": "github tools",
                 "tier": "safe", "status": "registered"},
            ],
            "skills": [
                {"key": "statistical-analysis", "name": "Stats", "description": "stats",
                 "category": "data", "tier": "safe", "status": "registered"},
            ],
        }

    monkeypatch.setattr(equipment_service.registry_service, "safe_menu", fake_safe_menu)

    async def fake_assert(kind, key, **kw):
        ok = {("toolset", "web_search_scraping"), ("toolset", "mcp_7"),
              ("skill", "statistical-analysis")}
        if (kind, key) not in ok:
            raise equipment_service.registry_service.NotAssignableError(key)

    monkeypatch.setattr(equipment_service.registry_service, "assert_assignable", fake_assert)

    class Resp:
        # mcp_7 is echoed into BOTH toolsets and mcps — it must surface only in mcps.
        content = ('{"toolsets":["web_search_scraping","mcp_7"],'
                   '"skills":["statistical-analysis"],'
                   '"mcps":["mcp_7"],"gaps":["实时榜单/营收数据"]}')

    class A:
        async def chat(self, system, user, **kw):
            return Resp()

    monkeypatch.setattr(equipment_service, "_get_adapter", lambda: A())

    out = await equipment_service.curate("拆解手游数值,需要实时榜单数据")
    assert out["toolsets"] == ["web_search_scraping"]  # mcp_7 excluded from toolsets
    assert "mcp_7" not in out["toolsets"]
    assert out["skills"] == ["statistical-analysis"]
    assert out["mcps"] == ["mcp_7"]
    assert out["gaps"] == ["实时榜单/营收数据"]


async def test_curate_drops_non_assignable_mcp_and_caps_gaps(monkeypatch):
    async def fake_safe_menu():
        return {
            "toolsets": [{"key": "mcp_7", "name": "GitHub MCP", "description": "gh",
                          "tier": "safe", "status": "registered"}],
            "skills": [],
        }

    monkeypatch.setattr(equipment_service.registry_service, "safe_menu", fake_safe_menu)

    async def fake_assert(kind, key, **kw):
        if (kind, key) != ("toolset", "mcp_7"):
            raise equipment_service.registry_service.NotAssignableError(key)

    monkeypatch.setattr(equipment_service.registry_service, "assert_assignable", fake_assert)

    class Resp:
        # mcp_7 valid, mcp_99 not assignable -> dropped; 8 gaps -> capped at 6
        content = ('{"toolsets":[],"skills":[],"mcps":["mcp_7","mcp_99"],'
                   '"gaps":["a","b","c","d","e","f","g","h"," "]}')

    class A:
        async def chat(self, system, user, **kw):
            return Resp()

    monkeypatch.setattr(equipment_service, "_get_adapter", lambda: A())

    out = await equipment_service.curate("need")
    assert out["mcps"] == ["mcp_7"]
    assert out["gaps"] == ["a", "b", "c", "d", "e", "f"]
    # toolsets fallback still kicks in (additive change must not break it)
    assert out["toolsets"] == ["web_search_scraping"]
