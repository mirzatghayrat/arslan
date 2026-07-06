"""Executors: keyed registry, availability checks, bounded extract output."""
import socket

import httpx
import pytest


@pytest.mark.asyncio
async def test_executor_map_covers_wired_tools():
    from server.registry.executors import EXECUTORS

    core = {"web_search", "web_extract", "render_chart", "create_skill", "render_deck", "run_python", "run_command"}
    assert core <= set(EXECUTORS)  # core tools present; extras (e.g. list_my_capabilities) allowed


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
    monkeypatch.setattr(executors, "_is_private_host", lambda url: False)
    out = await executors.EXECUTORS["web_extract"].execute({"url": "https://x"})
    assert out["ok"] is True
    assert len(out["text"]) <= executors._EXTRACT_CHAR_LIMIT + 20


# ---------------------------------------------------------------------------
# Scheme guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_web_extract_rejects_non_http_scheme():
    from server.registry.executors import EXECUTORS

    out = await EXECUTORS["web_extract"].execute({"url": "ftp://example.com/file"})
    assert out["ok"] is False
    assert "invalid" in out["error"].lower() or "url" in out["error"].lower()


@pytest.mark.asyncio
async def test_web_extract_rejects_missing_url():
    from server.registry.executors import EXECUTORS

    out = await EXECUTORS["web_extract"].execute({})
    assert out["ok"] is False
    assert "url" in out["error"].lower()


# ---------------------------------------------------------------------------
# SSRF / private-host guard
# ---------------------------------------------------------------------------

def _fake_getaddrinfo_loopback(host, port, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]


def _fake_getaddrinfo_link_local(host, port, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]


def _fake_getaddrinfo_public(host, port, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


def test_is_private_host_loopback(monkeypatch):
    """Direct helper test — loopback IP returns True."""
    from server.registry import executors

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_loopback)
    assert executors._is_private_host("http://127.0.0.1/x") is True


def test_is_private_host_link_local(monkeypatch):
    """Direct helper test — cloud metadata IP (169.254.169.254) returns True."""
    from server.registry import executors

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_link_local)
    assert executors._is_private_host("http://169.254.169.254/x") is True


def test_is_private_host_public(monkeypatch):
    """Direct helper test — a real public IP returns False."""
    from server.registry import executors

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_public)
    assert executors._is_private_host("http://example.com") is False


@pytest.mark.asyncio
async def test_web_extract_rejects_private_host(monkeypatch):
    """Executor rejects when _is_private_host returns True."""
    from server.registry import executors

    monkeypatch.setattr(executors, "_is_private_host", lambda url: True)
    out = await executors.EXECUTORS["web_extract"].execute(
        {"url": "https://internal.example"}
    )
    assert out["ok"] is False
    assert "private" in out["error"].lower() or "internal" in out["error"].lower()


# ---------------------------------------------------------------------------
# num_results validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_web_search_rejects_invalid_num_results(monkeypatch):
    from server.registry import executors

    class _P:
        async def search(self, query, num_results=5):
            return []

    async def _fake_provider():
        return _P()

    monkeypatch.setattr(executors, "_search_provider", _fake_provider)
    out = await executors.EXECUTORS["web_search"].execute(
        {"query": "test", "num_results": "not-a-number"}
    )
    assert out["ok"] is False
    assert "num_results" in out["error"]


@pytest.mark.asyncio
async def test_web_search_empty_query():
    from server.registry.executors import EXECUTORS

    out = await EXECUTORS["web_search"].execute({"query": ""})
    assert out["ok"] is False
    assert "query" in out["error"].lower()


# ---------------------------------------------------------------------------
# Error category mapping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_web_search_provider_raises_timeout(monkeypatch):
    """TimeoutException maps to 'timeout' category in error message."""
    from server.registry import executors

    class _P:
        async def search(self, query, num_results=5):
            raise httpx.TimeoutException("timed out")

    async def _fake_provider():
        return _P()

    monkeypatch.setattr(executors, "_search_provider", _fake_provider)
    out = await executors.EXECUTORS["web_search"].execute({"query": "test"})
    assert out["ok"] is False
    assert out["error"].startswith("search failed:")
    assert "timeout" in out["error"]


@pytest.mark.asyncio
async def test_web_extract_fetch_raises(monkeypatch):
    """_fetch_text raising propagates as ok=False with fetch failed prefix."""
    from server.registry import executors

    async def _bad_fetch(url):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(executors, "_fetch_text", _bad_fetch)
    # also ensure _is_private_host passes so we reach the fetch
    monkeypatch.setattr(executors, "_is_private_host", lambda url: False)
    out = await executors.EXECUTORS["web_extract"].execute({"url": "https://example.com"})
    assert out["ok"] is False
    assert out["error"].startswith("fetch failed:")
    assert "timeout" in out["error"]


# ---------------------------------------------------------------------------
# Empty-extract branch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_web_extract_empty_text(monkeypatch):
    """When _fetch_text returns empty string, executor returns no extractable text."""
    from server.registry import executors

    async def _empty_fetch(url):
        return ""

    monkeypatch.setattr(executors, "_fetch_text", _empty_fetch)
    monkeypatch.setattr(executors, "_is_private_host", lambda url: False)
    out = await executors.EXECUTORS["web_extract"].execute({"url": "https://example.com"})
    assert out["ok"] is False
    assert "extractable" in out["error"].lower()
