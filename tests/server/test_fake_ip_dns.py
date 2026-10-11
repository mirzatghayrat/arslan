"""0.1.61 §E: the web behind a fake-IP proxy.

On the user's Mac every name resolves into 198.18.0.0/15 (Clash-style fake-IP DNS),
and `not is_global` refused all of them: web_search, web_extract and the agent browser
had not worked since 2026-10-05 (spec §0.3). The rule now: a NAME whose IPv4 answers all
lie in the fake range passes when a proxy carries the request (the proxy resolves it),
or when the system DNS itself is fake-IP (a public canary resolves there too). Literal
addresses, local names, real private answers and mixed answers stay refused.
"""
from __future__ import annotations

import ipaddress
import socket
from types import SimpleNamespace

import httpx
import pytest

from server.registry import net_pin

FAKE = "198.18.0.33"
PUBLIC = "93.184.216.34"


def _addrinfo(*ips: str):
    return [((socket.AF_INET6 if ":" in ip else socket.AF_INET), socket.SOCK_STREAM, 6, "",
             (ip, 0)) for ip in ips]


def _resolver(monkeypatch, table: dict[str, tuple[str, ...]], default: tuple[str, ...] = (PUBLIC,)):
    """Answers per name; records every name asked, so the tests can count lookups. A literal
    address resolves to itself, as the real resolver does."""
    calls: list[str] = []

    def fake(host, *a, **k):
        calls.append(host)
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return _addrinfo(*table.get(host, default))
        return _addrinfo(host)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return calls


@pytest.fixture(autouse=True)
def no_proxy(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(net_pin, "getproxies", lambda: {})


@pytest.fixture
def seen(monkeypatch):
    """Nothing leaves the machine; every request that would have been sent is recorded."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="ok", headers={"content-type": "text/plain"})

    monkeypatch.setattr(net_pin, "_build_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False))
    return requests


def _with_proxy(monkeypatch):
    monkeypatch.setattr(net_pin, "getproxies", lambda: {"https": "http://127.0.0.1:7899",
                                                         "http": "http://127.0.0.1:7899"})
    monkeypatch.setattr(net_pin, "proxy_bypass", lambda host: False)


async def test_fake_answer_through_a_proxy_is_fetched_by_name(monkeypatch, seen):
    _with_proxy(monkeypatch)
    _resolver(monkeypatch, {"github.com": (FAKE,)})        # the canary stays PUBLIC
    resp = await net_pin.pinned_get("https://github.com/morluto/rea")
    assert resp.status_code == 200
    assert seen[0].url.host == "github.com"                  # delegated: the proxy resolves it


async def test_fake_answer_without_a_proxy_is_pinned_when_dns_is_fake_ip(monkeypatch, seen):
    _resolver(monkeypatch, {}, default=(FAKE,))             # every name, canary included
    await net_pin.pinned_get("https://github.com/morluto/rea")
    assert seen[0].url.host == FAKE                          # the address the TUN maps back
    assert seen[0].headers["host"] == "github.com"
    assert seen[0].extensions.get("sni_hostname") == "github.com"


async def test_fake_v4_with_v6_answers_pins_the_fake_v4(monkeypatch, seen):
    """mihomo with IPv6 answers A=fake plus an AAAA; nothing connects to the AAAA."""
    _resolver(monkeypatch, {"github.com": (FAKE, "2606:4700::6810:84e5")}, default=(FAKE,))
    await net_pin.pinned_get("https://github.com/")
    assert seen[0].url.host == FAKE


async def test_fake_answer_refused_when_dns_is_not_fake_ip_and_no_proxy(monkeypatch, seen):
    _resolver(monkeypatch, {"github.com": (FAKE,)})        # canary public: DNS is not fake-IP
    with pytest.raises(net_pin._BlockedHost):
        await net_pin.pinned_get("https://github.com/")
    assert not seen


@pytest.mark.parametrize("literal", [FAKE, "10.0.0.1", "127.0.0.1", "[::1]"])
@pytest.mark.parametrize("proxied", [False, True])
async def test_a_literal_address_is_never_fake(monkeypatch, seen, literal, proxied):
    """A literal address is judged as itself, in fake-IP mode and through a proxy alike."""
    if proxied:
        _with_proxy(monkeypatch)
    _resolver(monkeypatch, {}, default=(FAKE,))
    with pytest.raises(net_pin._BlockedHost):
        await net_pin.pinned_get(f"https://{literal}/")
    assert not seen


@pytest.mark.parametrize("answers", [("10.0.0.5",), ("127.0.0.1",), ("100.64.1.1",),
                                     ("192.168.1.10",), (FAKE, "127.0.0.1"),
                                     (FAKE, "192.168.1.10")])
async def test_real_private_and_mixed_answers_stay_refused_through_a_proxy(monkeypatch, seen,
                                                                           answers):
    _with_proxy(monkeypatch)
    _resolver(monkeypatch, {"evil.test": answers}, default=(FAKE,))
    with pytest.raises(net_pin._BlockedHost):
        await net_pin.pinned_get("https://evil.test/")
    assert not seen


@pytest.mark.parametrize("host", ["localhost", "LOCALHOST.", "app.localhost", "printer.local",
                                  "nas.lan", "metadata.google.internal", "router.home.arpa",
                                  "wiki.intranet", "files.corp"])
async def test_local_names_are_refused_whatever_dns_says(monkeypatch, seen, host):
    _with_proxy(monkeypatch)
    _resolver(monkeypatch, {}, default=(FAKE,))
    with pytest.raises(net_pin._BlockedHost):
        await net_pin.pinned_get(f"https://{host}/")
    assert not seen


async def test_a_configured_search_host_on_the_lan_still_works(monkeypatch, seen):
    """allow_host (a SearXNG address typed in Settings) keeps its exemption, local name too."""
    _resolver(monkeypatch, {"searx.lan": ("192.168.1.20",)})
    await net_pin.pinned_get("http://searx.lan/search", allow_host="searx.lan")
    assert seen


async def test_the_canary_is_asked_only_for_fake_answers(monkeypatch, seen):
    calls = _resolver(monkeypatch, {})                      # every answer public
    await net_pin.pinned_get("https://example.org/")
    assert calls == ["example.org"]                         # resolved once, no canary lookup


def test_a_blocked_address_is_named_not_unexpected():
    exc = net_pin._BlockedHost("github.com resolves to a private or internal address")
    assert net_pin.categorize(exc) == "blocked address (local network)"


async def test_web_search_reports_the_blocked_address(monkeypatch):
    from server.registry import executors

    class Refused:
        name = "duckduckgo"

        async def search(self, query, num_results=5):
            raise net_pin._BlockedHost("html.duckduckgo.com resolves to a private or internal address")

    async def provider():
        return SimpleNamespace(provider=Refused(), reason=None)

    monkeypatch.setattr(executors, "_search_provider", provider)
    out = await executors.WebSearchExecutor().execute({"query": "rea"})
    assert out["ok"] is False
    assert out["error"] == "search failed: blocked address (local network)"


# ── the edges of the exception ─────────────────────────────────────────────────────
# Added after the mutation check: widening the block to a /8, narrowing it to a /16, or
# pinning the first answer instead of the first IPv4 all survived the cases above.


@pytest.mark.parametrize("answer", ["198.18.0.0", "198.19.255.255"])
async def test_the_fake_block_is_the_whole_slash_15(monkeypatch, seen, answer):
    """First and last address of 198.18.0.0/15: the exception is RFC 2544's block, not a /16."""
    _with_proxy(monkeypatch)
    _resolver(monkeypatch, {"github.com": (answer,)})
    resp = await net_pin.pinned_get("https://github.com/")
    assert resp.status_code == 200
    assert seen[0].url.host == "github.com"


@pytest.mark.parametrize("proxied", [False, True])
async def test_a_non_public_neighbour_of_the_fake_block_stays_refused(monkeypatch, seen,
                                                                      proxied):
    """198.51.100.7 (TEST-NET-2) is neither global nor fake: the exception does not widen to
    198.0.0.0/8. (A PUBLIC neighbour is allowed by the ordinary rule, so it proves nothing.)"""
    if proxied:
        _with_proxy(monkeypatch)
    _resolver(monkeypatch, {"evil.test": ("198.51.100.7",)}, default=(FAKE,))
    with pytest.raises(net_pin._BlockedHost):
        await net_pin.pinned_get("https://evil.test/")
    assert not seen


async def test_the_fake_v4_is_pinned_when_a_v6_answer_comes_first(monkeypatch, seen):
    """getaddrinfo may lead with the AAAA; the address we pin is still the fake IPv4."""
    _resolver(monkeypatch, {"github.com": ("2606:4700::6810:84e5", FAKE)}, default=(FAKE,))
    await net_pin.pinned_get("https://github.com/")
    assert seen[0].url.host == FAKE


# ── a literal is a literal, however it is spelled ──────────────────────────────────
# Added with the fix for a gap found in review: the OS resolver reads these spellings as the
# address 198.18.0.33, `ipaddress` does not parse them, so they were taken for NAMES, and a
# name in the fake block is allowed. browser_proxy takes its CONNECT host from the page.


@pytest.mark.parametrize("proxied", [False, True])
@pytest.mark.parametrize("host", ["0xc6120021", "198.18.33", "3323068449"])
async def test_an_exotic_spelling_of_an_address_is_a_literal_not_a_name(monkeypatch, seen, host,
                                                                       proxied):
    """Hex, short-dotted and bare-decimal spellings of 198.18.0.33 are literal addresses, and
    a literal is never fake: refused with and without a proxy, in fake-IP mode."""
    assert socket.inet_aton(host) == socket.inet_aton(FAKE)     # the OS reads it as FAKE ...
    with pytest.raises(ValueError):
        ipaddress.ip_address(host)                               # ... and `ipaddress` does not
    if proxied:
        _with_proxy(monkeypatch)
    # Canary fake, and the spelling resolves to FAKE, as the real resolver does for it.
    _resolver(monkeypatch, {host: (FAKE,)}, default=(FAKE,))
    with pytest.raises(net_pin._BlockedHost):
        await net_pin.pinned_get(f"https://{host}/")
    assert not seen
