"""0.1.61 PR 1 follow-up: how `web_extract` introduces itself, and how it names a refusal.

On the user's Mac `web_extract("https://www.wikipedia.org/")` failed with a 403, "Please set a
user-agent and respect our robot policy". The page fetch sent no headers of its own, so httpx's
`python-httpx/x.y` went out, and many sites refuse that. `net_pin.categorize` then called the 403
`key-rejected`, a label for search API keys, so the model was told to fix a key that does not exist.

The rulings these tests hold:

1. A page read (`_fetch_text`, what `web_extract` calls) sends the agent user agent and an Accept
   header, each one only if the caller did not set it (`_page_headers`). `pinned_get` is a plain
   GET, exactly `pinned_request("GET")`: it adds nothing, and neither does `pinned_request`, which
   search and the connection tests share. A caller's `Host` is never sent, in any spelling, on
   either branch of `pinned_request`; pinning's own goes last.
2. `web_extract` names a refusal with `net_pin.categorize_page`: 401, 403 and 451 are `the site
   refused (http N)`, 429 stays `rate-limited`, any other status is `http N`. Search keeps
   `categorize`, where 401 and 403 still mean a rejected key.
3. The app's version is only a token in a header. An odd one (control characters, non-ASCII,
   absurdly long, none at all) or a broken config changes that token and never fails the read.

Hermetic like test_fake_ip_dns.py, and for the same reason: this project's Mac really is behind a
fake-IP proxy, where a real lookup answers an address that the TUN routes out to the internet.
There is no real resolver and no real transport here, even under a mutant: the autouse fixture
refuses both, and a test that wants an answer installs it with `serve`. The suite-wide guard in
tests/conftest.py is the backstop behind this file's own.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import h11
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

_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


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
    # NO_PROXY=* and NOT deleted: with no proxy variable at all, urllib on macOS falls back to the
    # SYSTEM proxy (127.0.0.1:7899 on this Mac), and a real client that code under test builds
    # would then send its request there.
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
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


async def test_a_page_fetch_sends_the_arslan_user_agent_and_accept(monkeypatch):
    """The bug itself: nothing was set, so httpx's own agent went out."""
    seen = serve(monkeypatch, _page)
    assert await net_pin._fetch_text("https://www.wikipedia.org/") == "plain page"
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
    for version in ("9.8.7", "0.1.61", "0.2.0-dev", "0.1.61+build.5_rc-1"):
        monkeypatch.setenv("ARSLAN_APP_VERSION", version)
        await net_pin._fetch_text("https://example.test/")
        assert seen[-1].headers["user-agent"] == UA.format(version=version)


async def test_without_the_packaged_env_the_version_is_the_helpers_fallback(monkeypatch):
    monkeypatch.delenv("ARSLAN_APP_VERSION", raising=False)
    seen = serve(monkeypatch, _page)
    await net_pin._fetch_text("https://example.test/")
    assert seen[0].headers["user-agent"] == UA.format(version=config._app_version())


@pytest.mark.parametrize("env,token", [
    pytest.param("1.2.3\r\nX-Injected: yes", "1.2.3X-Injectedyes", id="crlf-and-a-second-header"),
    pytest.param("1.2.3\nEvil", "1.2.3Evil", id="bare-lf"),
    pytest.param("1.0.0-é", "1.0.0-", id="non-ascii-suffix"),
    pytest.param("v 1.2 (beta; build 7)", "v1.2betabuild7", id="spaces-and-punctuation"),
    pytest.param("日本語", "unknown", id="nothing-left"),
    pytest.param("１２３", "unknown", id="fullwidth-digits-are-not-digits"),
    pytest.param("x" * 100, "x" * 40, id="cut-to-40"),
])
async def test_an_odd_version_changes_the_token_and_never_fails_the_read(monkeypatch, env, token):
    """On the real wire h11 refuses CR, LF and the like in a header value, and the ASCII codec
    refuses the rest: before this, such a version failed EVERY page read."""
    monkeypatch.setenv("ARSLAN_APP_VERSION", env)
    seen = serve(monkeypatch, _page)
    assert await net_pin._fetch_text("https://example.test/") == "plain page"
    agent = seen[0].headers["user-agent"]
    assert agent == UA.format(version=token)
    assert agent.isascii() and agent.isprintable()
    # and a legal header value: the same check the real wire makes (this raises for CR, LF, NUL)
    h11.Request(method="GET", target="/", headers=[("Host", "example.test"), ("User-Agent", agent)])


@pytest.mark.parametrize("conf,token", [
    pytest.param('{"version": "0.9.9"}', "0.9.9-dev", id="control-a-real-file-is-read"),
    pytest.param("[]", "unknown", id="root-is-a-list"),
    pytest.param('"text"', "unknown", id="root-is-a-string"),
    pytest.param("7", "unknown", id="root-is-a-number"),
    pytest.param("null", "unknown", id="root-is-null"),
    pytest.param("{}", "unknown", id="no-version-key"),
    pytest.param("{not json", "unknown", id="invalid-json"),
    pytest.param(None, "unknown", id="no-file"),
])
async def test_a_config_that_is_not_a_version_object_cannot_fail_the_read(
        monkeypatch, tmp_path, conf, token):
    """`config._app_version()` catches OSError, ValueError and KeyError, and a JSON root that is not
    an object raises TypeError. The page read must not depend on the file being well formed."""
    monkeypatch.delenv("ARSLAN_APP_VERSION", raising=False)
    (tmp_path / "server").mkdir()
    if conf is not None:
        (tmp_path / "desktop" / "src-tauri").mkdir(parents=True)
        (tmp_path / "desktop" / "src-tauri" / "tauri.conf.json").write_text(conf)
    monkeypatch.setattr(config, "__file__", str(tmp_path / "server" / "config.py"))
    seen = serve(monkeypatch, _page)
    assert await net_pin._fetch_text("https://example.test/") == "plain page"
    assert seen[0].headers["user-agent"] == UA.format(version=token)


async def test_a_version_helper_that_raises_cannot_fail_the_read(monkeypatch):
    def broken():
        raise RuntimeError("boom")

    monkeypatch.setattr(config, "_app_version", broken)
    seen = serve(monkeypatch, _page)
    assert await net_pin._fetch_text("https://example.test/") == "plain page"
    assert seen[0].headers["user-agent"] == UA.format(version="unknown")


def test_importing_net_pin_does_not_load_the_app_config(tmp_path):
    """net_pin is imported by everything that fetches. `server.config` reads settings and secrets
    the moment it is imported, and only a page read's agent name needs the version, so that is
    where it is looked up. A fresh interpreter, with its own HOME and data dir."""
    repo = Path(__file__).resolve().parents[2]
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": str(repo),
           "HOME": str(tmp_path), "ARSLAN_DATA_DIR": str(tmp_path / "data"),
           "ARSLAN_SECRET_KEY_FILE": ""}
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys, server.registry.net_pin; print('server.config' in sys.modules)"],
        cwd=repo, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


@pytest.mark.parametrize("name", ["User-Agent", "user-agent", "USER-AGENT"])
def test_a_callers_own_user_agent_wins(name):
    """Header names are case-insensitive: a second spelling must not go out beside the caller's."""
    headers = net_pin._page_headers({name: "Mine/1.0"})
    assert [value for key, value in headers.items() if key.lower() == "user-agent"] == ["Mine/1.0"]


@pytest.mark.parametrize("name", ["Accept", "accept"])
def test_a_callers_own_accept_wins(name):
    headers = net_pin._page_headers({name: "application/json"})
    assert [value for key, value in headers.items() if key.lower() == "accept"] == [
        "application/json"]


def test_each_default_is_its_own():
    """A caller who names its agent still gets the Accept default, and one who sets only Accept
    still gets the user agent: the defaults are not a pair that a caller takes or leaves."""
    assert net_pin._page_headers({"User-Agent": "Mine/1.0"})["Accept"] == ACCEPT
    assert net_pin._page_headers({"Accept": "text/csv"})["User-Agent"] == UA.format(version=VERSION)


def test_the_defaults_are_added_to_a_copy():
    given = {"X-Test": "1"}
    merged = net_pin._page_headers(given)
    assert merged["X-Test"] == "1" and "User-Agent" in merged and "Accept" in merged
    assert given == {"X-Test": "1"}
    assert net_pin._page_headers(None) == net_pin._page_headers({}) == net_pin._page_headers()


@pytest.mark.parametrize("name", ["User-Agent", "user-agent"])
async def test_a_callers_own_user_agent_reaches_the_wire_once(monkeypatch, name):
    seen = serve(monkeypatch, _page)
    await net_pin.pinned_get("https://example.test/",
                             headers=net_pin._page_headers({name: "Mine/1.0"}))
    assert seen[0].headers.get_list("user-agent") == ["Mine/1.0"]


async def test_every_hop_of_a_redirect_carries_them(monkeypatch):
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/first":
            return httpx.Response(302, headers={"location": "https://example.test/second"})
        return _page(request)

    seen = serve(monkeypatch, respond)
    assert await net_pin._fetch_text("https://example.test/first") == "plain page"
    assert len(seen) == 2
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


# ------------------------------------------------------------------ Host: the caller never sets it


@pytest.mark.parametrize("name", ["Host", "host", "HOST"])
async def test_no_header_can_overwrite_the_pinned_host(monkeypatch, name):
    """Pinning's own headers go last and alone. Header names are case-insensitive: a caller's `host`
    or `HOST` next to the pinned `Host` reaches httpx as two Host entries, and on a real wire h11
    refuses the request ("Found multiple Host: headers"). MockTransport does not validate, so this
    reads what the client built: the real name, exactly once, and the caller's value nowhere."""
    seen = serve(monkeypatch, _page)
    await net_pin.pinned_get("https://example.test:8443/page", headers={name: "evil.example"})
    request = seen[0]
    assert request.url.host == PUBLIC                                    # the validated address
    assert request.headers.get_list("host") == ["example.test:8443"]     # the real name, once
    assert request.extensions["sni_hostname"] == "example.test"


@pytest.mark.parametrize("name", ["Host", "host", "HOST"])
async def test_no_header_can_choose_the_host_of_a_delegated_proxy_request(monkeypatch, name):
    """The branch this Mac takes: with an https proxy set, the request goes by NAME and httpx builds
    the Host from the real URL. A caller's Host would replace that one, and the proxy would forward
    a request for one site with the Host of another."""
    seen = serve(monkeypatch, _page, dns=(FAKE,))
    _with_proxy(monkeypatch)
    await net_pin.pinned_get("https://www.wikipedia.org/", headers={name: "evil.example"})
    request = seen[0]
    assert request.url.host == "www.wikipedia.org"                       # by name: delegated
    assert request.headers.get_list("host") == ["www.wikipedia.org"]


@pytest.mark.parametrize("branch", ["pinned", "proxy"])
async def test_the_other_caller_headers_still_pass_on_both_branches(monkeypatch, branch):
    seen = serve(monkeypatch, _page, dns=(PUBLIC,) if branch == "pinned" else (FAKE,))
    if branch == "proxy":
        _with_proxy(monkeypatch)
    await net_pin.pinned_get("https://www.wikipedia.org/",
                             headers={"X-Test": "1", "host": "evil.example", "Accept": "text/csv"})
    request = seen[0]
    assert request.headers.get_list("x-test") == ["1"]
    assert request.headers.get_list("accept") == ["text/csv"]
    assert request.headers.get_list("host") == ["www.wikipedia.org"]


# ------------------------------------------------------------------ page reads only


async def test_pinned_get_and_pinned_request_are_plain_gets(monkeypatch):
    """The identity of a page read is `_fetch_text`'s. `pinned_get` stays the readable spelling of
    `pinned_request("GET")`: other callers (a JSON API, a connection test) send what they pass."""
    seen = serve(monkeypatch, _page)
    await net_pin.pinned_get("https://example.test/")
    await net_pin.pinned_request("GET", "https://example.test/")
    await net_pin.pinned_get("https://example.test/", headers={"User-Agent": "Mine/1.0"})
    for request in seen[:2]:
        assert "Arslan-User" not in request.headers["user-agent"]
        assert request.headers["accept"] != ACCEPT
    assert seen[2].headers.get_list("user-agent") == ["Mine/1.0"]


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


async def test_search_calls_a_401_a_rejected_key_and_a_403_a_block(monkeypatch):
    """Search keeps its own words, not the page ones. Since 0.1.63 D5 (card, ③Hands' review item 3) a 403
    from a search provider is the provider refusing to search (search_blocked); only a 401 is the key."""
    async def config_of_a_keyed_provider():
        return executors.SearchConfig(name="tavily", key="k", key_state="set")

    monkeypatch.setattr(executors, "_read_search_config", config_of_a_keyed_provider)
    seen = serve(monkeypatch, _status(401))
    out = await executors.WebSearchExecutor().execute({"query": "anything"})
    assert out == {"ok": False, "code": "search_failed", "provider": "tavily",
                   "error": "search failed: key-rejected — the search key was rejected: re-enter it in Settings"}
    assert "Arslan-User" not in seen[0].headers["user-agent"]     # search is not a page read
    serve(monkeypatch, _status(403))
    out = await executors.WebSearchExecutor().execute({"query": "anything"})
    assert out["code"] == "search_blocked" and "the site refused" not in out["error"]


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
