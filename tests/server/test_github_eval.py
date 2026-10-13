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
        async def get(self, url, headers=None):
            _Client.last = {"url": url, "headers": headers}
            return _Resp()
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


# ── a renamed or transferred repository (0.1.61 PR 6): GitHub answers its old name with a 301 ──────────

def _github(monkeypatch, handler):
    """api.github.com as MockTransport serves it; `seen` is every request that was made, in order."""
    seen: list[httpx.Request] = []

    def record(request):
        seen.append(request)
        return handler(request)
    real = httpx.AsyncClient

    class Client(real):
        def __init__(self, *a, **kw):
            kw.setdefault("transport", httpx.MockTransport(record))
            super().__init__(*a, **kw)
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    monkeypatch.setattr(ge, "_token", lambda: _noop_token())
    return seen


def _repo_json(full_name="new-owner/new-name"):
    return {"full_name": full_name, "html_url": f"https://github.com/{full_name}", "stargazers_count": 5,
            "forks_count": 1, "license": {"spdx_id": "MIT"}, "pushed_at": "2026-06-01T00:00:00Z",
            "description": "", "topics": []}


async def test_a_renamed_repository_resolves_through_its_redirect(monkeypatch):
    def handler(request):
        if request.url.path == "/repos/old-owner/old-name":
            return httpx.Response(301, headers={"Location": "https://api.github.com/repositories/42"})
        assert request.url.path == "/repositories/42"
        return httpx.Response(200, json=_repo_json())
    seen = _github(monkeypatch, handler)
    meta = await ge.fetch_repo("old-owner", "old-name")
    assert meta["full_name"] == "new-owner/new-name"                    # the name it has now
    assert [r.url.path for r in seen] == ["/repos/old-owner/old-name", "/repositories/42"]


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
async def test_a_relative_redirect_stays_on_the_api_host(monkeypatch, status):
    def handler(request):
        if request.url.path == "/repos/o/r":
            return httpx.Response(status, headers={"Location": "/repositories/7"})
        return httpx.Response(200, json=_repo_json())
    seen = _github(monkeypatch, handler)
    assert (await ge.fetch_repo("o", "r"))["full_name"] == "new-owner/new-name"
    assert [(r.url.host, r.url.path) for r in seen] == [("api.github.com", "/repos/o/r"),
                                                         ("api.github.com", "/repositories/7")]


@pytest.mark.parametrize("target", [
    "https://evil.example/repositories/42",                  # another host
    "http://api.github.com/repositories/42",                 # a downgrade to plain http
    "https://api.github.com.evil.example/repositories/42",   # a host that only starts like it
    "https://api.github.com:8443/repositories/42",           # another port
    "https://user@api.github.com/repositories/42",           # credentials in the address
    "https://codeload.github.com/o/r/tar.gz/HEAD",           # GitHub's other host: not for metadata
])
async def test_a_redirect_off_api_github_com_is_refused_and_not_followed(monkeypatch, target):
    seen = _github(monkeypatch, lambda request: httpx.Response(301, headers={"Location": target}))
    with pytest.raises(ValueError, match="api.github.com"):
        await ge.fetch_repo("old-owner", "old-name")
    assert len(seen) == 1                                           # the other address was never asked


async def test_the_token_goes_only_to_api_github_com(monkeypatch):
    async def secret():
        return "not-a-real-token"
    seen = _github(monkeypatch, lambda request: httpx.Response(301, headers={"Location": "https://evil.example/x"}))
    monkeypatch.setattr(ge, "_token", secret)
    with pytest.raises(ValueError):
        await ge.fetch_repo("o", "r")
    assert [r.url.host for r in seen] == ["api.github.com"]          # evil.example was never asked...
    assert seen[0].headers["Authorization"] == "Bearer not-a-real-token"      # ...and the token did go to the API


async def test_the_token_is_on_every_hop_to_the_api(monkeypatch):
    """A renamed PRIVATE repository must still resolve: the redirected request carries the token too."""
    async def secret():
        return "not-a-real-token"

    def handler(request):
        if request.url.path == "/repos/o/r":
            return httpx.Response(301, headers={"Location": "/repositories/9"})
        return httpx.Response(200, json=_repo_json())
    seen = _github(monkeypatch, handler)
    monkeypatch.setattr(ge, "_token", secret)
    await ge.fetch_repo("o", "r")
    assert [r.headers.get("authorization") for r in seen] == ["Bearer not-a-real-token"] * 2


@pytest.mark.parametrize("location", ["javascript:alert(1)", "data:text/plain,hi", "mailto:a@b.c", "https:evil.example/x"])
async def test_a_location_with_a_scheme_and_no_host_is_a_refusal_not_an_InvalidURL(monkeypatch, location):
    """httpx builds the next request itself, followed or not, and raises InvalidURL (not an HTTPError, not
    a ValueError) for a Location that has a scheme and no host: that must come out as a plain refusal."""
    seen = _github(monkeypatch, lambda request: httpx.Response(301, headers={"Location": location}))
    with pytest.raises(ValueError, match="an address that is not one"):
        await ge.fetch_repo("o", "r")
    assert len(seen) == 1


async def test_at_most_three_redirects_are_followed(monkeypatch):
    def chain(hops):
        def handler(request):
            n = int(request.url.path.rsplit("/", 1)[-1]) if request.url.path.startswith("/hop/") else 0
            if n < hops:
                return httpx.Response(301, headers={"Location": f"https://api.github.com/hop/{n + 1}"})
            return httpx.Response(200, json=_repo_json())
        return handler
    seen = _github(monkeypatch, chain(3))
    assert (await ge.fetch_repo("o", "r"))["full_name"] == "new-owner/new-name"
    assert len(seen) == 4                                           # the request and its three redirects
    seen = _github(monkeypatch, chain(4))
    with pytest.raises(ValueError, match="too many"):
        await ge.fetch_repo("o", "r")
    assert len(seen) == 4                                           # the fourth redirect was not followed


async def test_a_redirect_without_a_location_is_still_an_error(monkeypatch):
    _github(monkeypatch, lambda request: httpx.Response(301))
    with pytest.raises(httpx.HTTPStatusError):
        await ge.fetch_repo("o", "r")
