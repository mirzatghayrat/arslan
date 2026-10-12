"""0.1.61 PR 1 follow-up: how `web_extract` introduces itself, and how it names a refusal.

On the user's Mac `web_extract("https://www.wikipedia.org/")` failed with a 403, "Please set a
user-agent and respect our robot policy". The page fetch sent no headers of its own, so httpx's
`python-httpx/x.y` went out, and many sites refuse that. `net_pin.categorize` then called the 403
`key-rejected`, a label for search API keys, so the model was told to fix a key that does not exist.

The rulings these tests hold:

1. A page read (`pinned_get`, so `_fetch_text`) sends the agent user agent and an Accept header,
   each one only if the caller did not set it. The pinning code still puts `Host` last. Search
   (`pinned_request`) is not a page read and gets neither default.
2. `web_extract` names a refusal with `net_pin.categorize_page`: 401, 403 and 451 are `the site
   refused (http N)`, 429 stays `rate-limited`, any other status is `http N`. Search keeps
   `categorize`, where 401 and 403 still mean a rejected key.

Hermetic like test_fake_ip_dns.py, and for the same reason: this project's Mac really is behind a
fake-IP proxy, where a real lookup answers an address that the TUN routes out to the internet.
There is no real resolver and no real transport here, even under a mutant: the autouse fixture
refuses both, and a test that wants an answer installs it with `serve`.
"""
from __future__ import annotations

import socket

import httpx
import pytest

from server import config
from server.registry import executors, net_pin, search_providers

PUBLIC = "93.184.216.34"
FAKE = "198.18.0.33"

#: The agent user agent, as ruled. Written out here and not imported, so that a changed constant in
#: net_pin cannot quietly change what the test expects.
UA = "Mozilla/5.0 (compatible; Arslan-User/{version}; +https://github.com/mirzatghayrat/arslan)"
ACCEPT = "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8"
VERSION = "9.8.7"

_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
               "http_proxy", "https_proxy", "all_proxy", "no_proxy")


def _addrinfo(*ips: str):
    return [((socket.AF_INET6 if ":" in ip else socket.AF_INET), socket.SOCK_STREAM, 6, "",
             (ip, 0)) for ip in ips]


@pytest.fixture(autouse=True)
def hermetic(monkeypatch):
    """No real resolver, no real transport, no proxy, and a known app version."""
    def no_resolver(host, *a, **k):
        raise socket.gaierror(socket.EAI_NONAME, f"test guard: no resolver for {host!r}")

    def no_network(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("test guard: no network", request=request)

    monkeypatch.setattr(socket, "getaddrinfo", no_resolver)
    monkeypatch.setattr(net_pin, "_build_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(no_network), follow_redirects=False, trust_env=False))
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(net_pin, "getproxies", lambda: {})
    monkeypatch.setattr(net_pin, "_delegation_warned", {})
    monkeypatch.setenv("ARSLAN_APP_VERSION", VERSION)


def serve(monkeypatch, respond, *, dns: tuple[str, ...] = (PUBLIC,)) -> list[httpx.Request]:
    """Every name resolves to `dns`; every request the code sends is recorded, then answered by
    `respond(request)`. Nothing leaves the machine."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond(request)

    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: _addrinfo(*dns))
    monkeypatch.setattr(net_pin, "_build_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False))
    return seen


def _page(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="plain page", headers={"content-type": "text/plain"})


def _status(code: int):
    return lambda request: httpx.Response(code, text="no", headers={"content-type": "text/plain"})


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/")
    return httpx.HTTPStatusError("boom", request=request,
                                 response=httpx.Response(code, request=request))


def _with_proxy(monkeypatch) -> None:
    monkeypatch.setattr(net_pin, "getproxies", lambda: {"https": "http://127.0.0.1:7899",
                                                         "http": "http://127.0.0.1:7899"})
    monkeypatch.setattr(net_pin, "proxy_bypass", lambda host: False)


# ------------------------------------------------------------------ the user agent and Accept


@pytest.mark.parametrize("fetch", [net_pin.pinned_get, net_pin._fetch_text],
                         ids=["pinned_get", "_fetch_text"])
async def test_a_page_fetch_sends_the_arslan_user_agent_and_accept(monkeypatch, fetch):
    """The bug itself: nothing was set, so httpx's own agent went out."""
    seen = serve(monkeypatch, _page)
    await fetch("https://www.wikipedia.org/")
    request = seen[0]
    assert request.headers.get_list("user-agent") == [UA.format(version=VERSION)]
    assert request.headers.get_list("accept") == [ACCEPT]
    assert "python-httpx" not in request.headers["user-agent"]
    assert request.headers.get_list("host") == ["www.wikipedia.org"]      # still the pinned name


async def test_web_extract_reads_a_site_that_refuses_the_default_httpx_agent(monkeypatch):
    """End to end, the user's case: the site answers 403 to a library's own name and serves a
    reader that names itself."""
    def wikimedia(request: httpx.Request) -> httpx.Response:
        if request.headers.get("user-agent", "").startswith("python-httpx"):
            return httpx.Response(403, text="Please set a user-agent and respect our robot policy")
        return httpx.Response(200, text="Wikipedia, the free encyclopedia",
                              headers={"content-type": "text/plain"})

    serve(monkeypatch, wikimedia)
    out = await executors.WebExtractExecutor().execute({"url": "https://www.wikipedia.org/"})
    assert out["ok"] is True and out["text"] == "Wikipedia, the free encyclopedia"


async def test_the_version_is_the_app_versions_and_not_a_constant(monkeypatch):
    seen = serve(monkeypatch, _page)
    for version in ("9.8.7", "0.1.61", "0.2.0-dev"):
        monkeypatch.setenv("ARSLAN_APP_VERSION", version)
        await net_pin.pinned_get("https://example.test/")
        assert seen[-1].headers["user-agent"] == UA.format(version=version)


async def test_without_the_packaged_env_the_version_is_the_helpers_fallback(monkeypatch):
    monkeypatch.delenv("ARSLAN_APP_VERSION", raising=False)
    seen = serve(monkeypatch, _page)
    await net_pin.pinned_get("https://example.test/")
    assert seen[0].headers["user-agent"] == UA.format(version=config._app_version())


@pytest.mark.parametrize("name", ["User-Agent", "user-agent", "USER-AGENT"])
async def test_a_callers_own_user_agent_wins(monkeypatch, name):
    """Header names are case-insensitive: a second spelling must not go out beside the caller's."""
    seen = serve(monkeypatch, _page)
    await net_pin.pinned_get("https://example.test/", headers={name: "Mine/1.0"})
    assert seen[0].headers.get_list("user-agent") == ["Mine/1.0"]


@pytest.mark.parametrize("name", ["Accept", "accept"])
async def test_a_callers_own_accept_wins(monkeypatch, name):
    seen = serve(monkeypatch, _page)
    await net_pin.pinned_get("https://example.test/", headers={name: "application/json"})
    assert seen[0].headers.get_list("accept") == ["application/json"]


async def test_each_default_is_its_own(monkeypatch):
    """A caller who names its agent still gets the Accept default, and one who sets only Accept
    still gets the user agent: the defaults are not a pair that a caller takes or leaves."""
    seen = serve(monkeypatch, _page)
    await net_pin.pinned_get("https://example.test/", headers={"User-Agent": "Mine/1.0"})
    await net_pin.pinned_get("https://example.test/", headers={"Accept": "application/json"})
    assert seen[0].headers.get_list("accept") == [ACCEPT]
    assert seen[1].headers.get_list("user-agent") == [UA.format(version=VERSION)]


async def test_every_hop_of_a_redirect_carries_them(monkeypatch):
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/first":
            return httpx.Response(302, headers={"location": "https://example.test/second"})
        return _page(request)

    seen = serve(monkeypatch, respond)
    response = await net_pin.pinned_get("https://example.test/first")
    assert response.status_code == 200 and len(seen) == 2
    for request in seen:
        assert request.headers.get_list("user-agent") == [UA.format(version=VERSION)]
        assert request.headers.get_list("accept") == [ACCEPT]
        assert request.headers.get_list("host") == ["example.test"]


@pytest.mark.parametrize("path", ["pinned", "tun", "proxy"])
async def test_every_way_the_request_can_leave_carries_them(monkeypatch, path):
    """The pinned address, the fake-IP TUN's stand-in address, and the delegated proxy branch,
    which sends the request by name: the one this Mac takes when it has a proxy set."""
    seen = serve(monkeypatch, _page, dns=(PUBLIC,) if path == "pinned" else (FAKE,))
    if path == "proxy":
        _with_proxy(monkeypatch)
    await net_pin._fetch_text("https://www.wikipedia.org/")
    request = seen[0]
    # the parametrisation means what it says: where the request really went
    assert request.url.host == {"pinned": PUBLIC, "tun": FAKE, "proxy": "www.wikipedia.org"}[path]
    assert request.headers.get_list("user-agent") == [UA.format(version=VERSION)]
    assert request.headers.get_list("accept") == [ACCEPT]


# ------------------------------------------------------------------ Host stays the pinned name


@pytest.mark.parametrize("name", ["Host", "host", "HOST"])
async def test_no_header_can_overwrite_the_pinned_host(monkeypatch, name):
    """Pinning's own headers go last. Header names are case-insensitive, so the lower-case and
    upper-case spellings must not reach the wire beside the pinned `Host` either: a request line
    to the validated address with `host: evil` next to the real one is ambiguous."""
    seen = serve(monkeypatch, _page)
    await net_pin.pinned_get("https://example.test:8443/page", headers={name: "evil.example"})
    request = seen[0]
    assert request.url.host == PUBLIC                                    # the validated address
    assert request.headers.get_list("host") == ["example.test:8443"]     # the real name, once
    assert request.extensions["sni_hostname"] == "example.test"


# ------------------------------------------------------------------ page reads only


async def test_the_search_path_is_not_a_page_read(monkeypatch):
    seen = serve(monkeypatch, lambda request: httpx.Response(200, json={"results": []}))
    await net_pin.pinned_request("GET", "https://api.example.test/search")
    await net_pin.pinned_request("POST", "https://api.example.test/search", json={})
    assert len(seen) == 2
    for request in seen:
        assert "Arslan-User" not in request.headers["user-agent"]
        assert request.headers["accept"] != ACCEPT


async def test_duckduckgo_keeps_its_own_user_agent(monkeypatch):
    seen = serve(monkeypatch, lambda request: httpx.Response(200, text="<html></html>"))
    provider = search_providers.DuckDuckGoHtmlProvider()
    assert await provider.search("anything") == []
    assert seen[0].headers.get_list("user-agent") == [provider._UA]


# ------------------------------------------------------------------ labels: a page, and search


@pytest.mark.parametrize("code", [401, 403, 451])
def test_a_page_that_refuses_us_is_the_sites_refusal(code):
    assert net_pin.categorize_page(_status_error(code)) == f"the site refused (http {code})"


def test_a_page_rate_limit_stays_rate_limited():
    assert net_pin.categorize_page(_status_error(429)) == "rate-limited"


@pytest.mark.parametrize("code", [400, 402, 404, 410, 418, 500, 502, 503])
def test_any_other_page_status_is_its_number(code):
    """402 included: `quota-exhausted` is advice about a search provider's quota, and a page
    that answers Payment Required has no quota for the user to top up."""
    assert net_pin.categorize_page(_status_error(code)) == f"http {code}"


@pytest.mark.parametrize("exc,expected", [
    (httpx.TimeoutException("slow"), "timeout"),
    (httpx.ConnectError("no route"), "network error"),
    (httpx.HTTPError("too many redirects"), "network error"),
    (ValueError("?"), "unexpected error"),
    (net_pin._BlockedHost(), "blocked address (local network)"),
    (net_pin._Unresolvable(), "cannot resolve"),
    (net_pin._NotConfiguredHost(), "not the configured search host"),
    (net_pin._FakeIpOnlyHttps(), "behind fake-IP DNS only https:// on port 443 is fetched"),
    (net_pin._InvalidHost(), "invalid host name"),
], ids=lambda value: type(value).__name__ if isinstance(value, Exception) else None)
def test_everything_that_is_not_a_status_is_named_as_before(exc, expected):
    assert net_pin.categorize_page(exc) == expected
    assert net_pin.categorize(exc) == expected


@pytest.mark.parametrize("code,expected", [
    (401, "key-rejected"), (403, "key-rejected"), (402, "quota-exhausted"),
    (429, "rate-limited"), (451, "http 451"), (404, "http 404"),
])
def test_search_keeps_its_own_words_for_a_status(code, expected):
    """`categorize` is the search vocabulary and does not change: there a 401 or 403 is the
    provider rejecting the API key the user entered."""
    assert net_pin.categorize(_status_error(code)) == expected


async def test_search_still_calls_a_403_a_rejected_key(monkeypatch):
    seen = serve(monkeypatch, _status(403))

    async def config_of_a_keyed_provider():
        return executors.SearchConfig(name="tavily", key="k", key_state="set")

    monkeypatch.setattr(executors, "_read_search_config", config_of_a_keyed_provider)
    out = await executors.WebSearchExecutor().execute({"query": "anything"})
    assert out == {"ok": False, "error": "search failed: key-rejected", "provider": "tavily"}
    assert "Arslan-User" not in seen[0].headers["user-agent"]     # search is not a page read


# ------------------------------------------------------------------ web_extract uses the page words


@pytest.mark.parametrize("code", [401, 403, 451])
async def test_web_extract_calls_a_refusal_the_sites(monkeypatch, code):
    serve(monkeypatch, _status(code))
    out = await executors.WebExtractExecutor().execute({"url": "https://www.wikipedia.org/"})
    assert out["ok"] is False
    assert out["error"].startswith(
        f"fetch failed: the site refused (http {code}) — do not retry this URL; ")
    assert "key-rejected" not in out["error"]


@pytest.mark.parametrize("code,label", [(429, "rate-limited"), (402, "http 402"),
                                        (404, "http 404"), (500, "http 500")])
async def test_web_extract_names_the_other_statuses(monkeypatch, code, label):
    serve(monkeypatch, _status(code))
    out = await executors.WebExtractExecutor().execute({"url": "https://www.wikipedia.org/"})
    assert out["ok"] is False
    assert out["error"].startswith(f"fetch failed: {label} — do not retry this URL; ")
    assert "quota-exhausted" not in out["error"]


async def test_web_extract_still_names_the_guards_refusals_apart(monkeypatch):
    """The network guard's own refusal is still `url refused: <label>`, and sends nothing."""
    seen = serve(monkeypatch, _page, dns=("127.0.0.1",))
    out = await executors.WebExtractExecutor().execute({"url": "https://evil.test/"})
    assert out == {"ok": False, "error": "url refused: blocked address (local network)"}
    assert not seen
