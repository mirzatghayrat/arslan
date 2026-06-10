"""Executors: keyed registry, availability checks, bounded extract output."""
import pytest


@pytest.mark.asyncio
async def test_executor_map_covers_wired_tools():
    from server.registry.executors import EXECUTORS

    assert set(EXECUTORS) == {"web_search", "web_extract"}


@pytest.mark.asyncio
async def test_web_search_executor_uses_provider(monkeypatch):
    from server.registry import executors

    class _P:
        name = "tavily"

        async def search(self, query, num_results=5):
            return [{"title": "T", "url": "https://a", "snippet": "s"}]

    async def _fake_provider():
        return _P()

    monkeypatch.setattr(executors, "_search_provider", _fake_provider)
    out = await executors.EXECUTORS["web_search"].execute({"query": "硬防晒 趋势"})
    assert out["ok"] is True
    assert out["results"][0]["url"] == "https://a"


@pytest.mark.asyncio
async def test_web_search_unavailable_without_key(monkeypatch):
    from server.registry import executors

    async def _no_provider():
        return None

    monkeypatch.setattr(executors, "_search_provider", _no_provider)
    out = await executors.EXECUTORS["web_search"].execute({"query": "x"})
    assert out["ok"] is False and "key" in out["error"].lower()


@pytest.mark.asyncio
async def test_web_extract_truncates(monkeypatch):
    from server.registry import executors

    async def _fake_fetch(url):
        return "word " * 50_000

    monkeypatch.setattr(executors, "_fetch_text", _fake_fetch)
    out = await executors.EXECUTORS["web_extract"].execute({"url": "https://x"})
    assert out["ok"] is True
    assert len(out["text"]) <= executors._EXTRACT_CHAR_LIMIT + 20
