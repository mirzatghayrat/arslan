import httpx
import pytest

from server.services import github_eval as ge


def _stub_search(monkeypatch, *, status, json_body=None, text=""):
    class _Resp:
        status_code = status
        def __init__(self):
            self._j = json_body or {}
            self.text = text
        def json(self): return self._j
        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("e", request=None, response=None)
    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None, params=None):
            _Client.last = {"url": url, "params": params}
            return _Resp()
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return _Client


async def _noop_token(): return ""


async def test_search_parses_and_inlines_trust(monkeypatch):
    monkeypatch.setattr(ge, "_token", _noop_token)
    cli = _stub_search(monkeypatch, status=200, json_body={"items": [
        {"full_name": "o/a", "html_url": "ha", "stargazers_count": 1500, "forks_count": 3,
         "license": {"spdx_id": "MIT"}, "pushed_at": "2026-06-20T00:00:00Z", "description": "mcp a"},
        {"full_name": "o/b", "html_url": "hb", "stargazers_count": 5, "forks_count": 0,
         "license": None, "pushed_at": "2026-01-01T00:00:00Z", "description": "mcp b"},
    ]})
    out = await ge.search_repos("mcp filesystem")
    assert cli.last["url"].startswith("https://api.github.com/search/repositories")
    assert cli.last["params"]["q"] == "mcp filesystem"
    assert len(out) == 2
    assert out[0]["full_name"] == "o/a" and out[0]["stars"] == 1500
    assert out[0]["trust"]["tier"] == "high"            # 1500★ + recent
    assert out[1]["trust"]["tier"] == "low"             # 5★
    assert "commercial" in out[0]["trust"]["license_note"].lower()


async def test_search_empty_query(monkeypatch):
    with pytest.raises(ValueError, match="query"):
        await ge.search_repos("   ")


async def test_search_rate_limited(monkeypatch):
    monkeypatch.setattr(ge, "_token", _noop_token)
    _stub_search(monkeypatch, status=403, text="API rate limit exceeded")
    with pytest.raises(ValueError, match="GITHUB_TOKEN"):
        await ge.search_repos("mcp")
