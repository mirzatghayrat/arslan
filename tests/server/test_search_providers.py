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
    """Parsing is this test's subject, so it stubs the TRANSPORT SEAM, not httpx.

    It used to replace `search_providers.httpx.AsyncClient` with a fake exposing only
    `.post` — reaching two layers down to a client the provider no longer builds.
    Every outbound request now goes through `net_pin.pinned_request`, which is where a
    parsing test should stop.
    """
    import httpx

    from server.registry import net_pin, search_providers

    async def fake(method, url, **kw):
        assert method == "POST"
        assert kw["json"]["query"] == "q"
        return httpx.Response(
            200,
            json={"results": [
                {"title": "T1", "url": "https://a", "content": "snippet one"},
                {"title": "T2", "url": "https://b", "content": "snippet two"},
            ]},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(net_pin, "pinned_request", fake)
    p = search_providers.get_provider("tavily", api_key="k")
    out = await p.search("q", num_results=2)
    assert [r["title"] for r in out] == ["T1", "T2"]
    assert all({"title", "url", "snippet"} <= set(r) for r in out)
