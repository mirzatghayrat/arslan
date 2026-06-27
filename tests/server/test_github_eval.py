import anyio
import httpx
import pytest

from server.services import github_eval as ge


def test_parse_repo_ref():
    assert ge.parse_repo_ref("owner/repo") == ("owner", "repo")
    assert ge.parse_repo_ref("https://github.com/modelcontextprotocol/servers") == ("modelcontextprotocol", "servers")
    assert ge.parse_repo_ref("https://github.com/a/b/tree/main/x") == ("a", "b")
    assert ge.parse_repo_ref("not a repo") is None
    assert ge.parse_repo_ref("") is None


def test_trust_tier():
    assert ge.trust_tier(2000, 30) == "high"
    assert ge.trust_tier(2000, 400) == "medium"      # popular but stale → not high
    assert ge.trust_tier(2000, None) == "medium"
    assert ge.trust_tier(150, 10) == "medium"
    assert ge.trust_tier(50, 10) == "low"


def test_license_note():
    assert "commercial" in ge.license_note("MIT").lower()
    assert "commercial" in ge.license_note("Apache-2.0").lower()
    assert ge.license_note("GPL-3.0") != ge.license_note("MIT")
    assert ge.license_note(None)


def _stub_client(monkeypatch, *, status, json_body=None, text=""):
    class _Resp:
        status_code = status
        def __init__(self): self._j = json_body or {}; self.text = text
        def json(self): return self._j
        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("e", request=None, response=None)
    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None): _Client.last = {"url": url, "headers": headers}; return _Resp()
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return _Client


async def test_fetch_repo_parses(monkeypatch):
    monkeypatch.setattr(ge, "_token", lambda: _noop_token())
    _stub_client(monkeypatch, status=200, json_body={
        "full_name": "o/r", "html_url": "https://github.com/o/r", "stargazers_count": 1234,
        "forks_count": 56, "license": {"spdx_id": "MIT"}, "pushed_at": "2026-06-01T00:00:00Z",
        "description": "an mcp server", "topics": ["mcp", "ai"]})
    meta = await ge.fetch_repo("o", "r")
    assert meta["stars"] == 1234 and meta["license"] == "MIT"
    assert meta["full_name"] == "o/r" and "mcp" in meta["topics"]
    assert isinstance(meta["pushed_days"], int)


async def test_fetch_repo_404(monkeypatch):
    monkeypatch.setattr(ge, "_token", lambda: _noop_token())
    _stub_client(monkeypatch, status=404)
    with pytest.raises(ValueError, match="not found"):
        await ge.fetch_repo("o", "r")


async def test_fetch_repo_rate_limited(monkeypatch):
    monkeypatch.setattr(ge, "_token", lambda: _noop_token())
    _stub_client(monkeypatch, status=403, text="API rate limit exceeded")
    with pytest.raises(ValueError, match="GITHUB_TOKEN"):
        await ge.fetch_repo("o", "r")


async def _noop_token():
    return ""
