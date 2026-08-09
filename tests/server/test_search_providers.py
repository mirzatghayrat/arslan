"""SearchProvider interface: swappable, Tavily default, no network in tests."""
import pytest


def test_provider_registry_default_and_swap():
    from server.registry.search_providers import get_provider

    p = get_provider("tavily", api_key="k")
    assert type(p).__name__ == "TavilyProvider"
    # 🔴 The default MOVED, deliberately: it is now the keyless fallback, so a fresh
    # install can search before signing up anywhere. Tavily is an upgrade, not a
    # prerequisite. This line is the product decision, not an implementation detail.
    assert get_provider("", api_key="").name == "duckduckgo"
    with pytest.raises(ValueError):
        get_provider("no-such-provider", api_key="k")


@pytest.mark.asyncio
async def test_tavily_parses_results(monkeypatch):
    from server.registry import search_providers

    class _Resp:
        status_code = 200

        def json(self):
            return {"results": [
                {"title": "T1", "url": "https://a", "content": "snippet one"},
                {"title": "T2", "url": "https://b", "content": "snippet two"},
            ]}

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, json=None, headers=None):
            assert json["query"] == "q"
            return _Resp()

    monkeypatch.setattr(search_providers.httpx, "AsyncClient", _Client)
    p = search_providers.get_provider("tavily", api_key="k")
    out = await p.search("q", num_results=2)
    assert [r["title"] for r in out] == ["T1", "T2"]
    assert all({"title", "url", "snippet"} <= set(r) for r in out)
