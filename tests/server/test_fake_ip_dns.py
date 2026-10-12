"""0.1.61 §E: the web behind a fake-IP proxy.

On the user's Mac every name resolves into 198.18.0.0/15 (Clash-style fake-IP DNS),
and `not is_global` refused all of them: web_search, web_extract and the agent browser
had not worked since 2026-10-05 (spec §0.3). The rule now: a NAME asked for over https:// on
port 443 whose IPv4 answers all lie in the fake range passes when a proxy carries the request
(the proxy resolves it), or when the system DNS itself is fake-IP (a public canary resolves
there too). Plain http and any other port are refused there (`_FakeIpOnlyHttps`): TLS against
the real name is what bounds the exception. Literal addresses (in any spelling), local names,
hosts with a control character, the TUN gateway 198.18.0.1, real private answers and mixed
answers stay refused, and a name is judged in its canonical form, the one the resolver and
the HTTP stack really use.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from types import SimpleNamespace

import httpx
import pytest

from server.registry import net_pin

FAKE = "198.18.0.33"
GATEWAY = "198.18.0.1"          # the TUN's own address: never a name's fake address
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
def hermetic(monkeypatch):
    """No real resolver and no real transport, even under a mutant: on this project's fake-IP
    Mac a real lookup answers a 198.18 address that the TUN routes out to the internet. Tests
    replace both with `_resolver` and `seen` (or their own); a test that forgets, or code that
    asks one more time than it should, fails here instead."""
    def no_resolver(host, *a, **k):
        raise socket.gaierror(socket.EAI_NONAME, f"test guard: no resolver for {host!r}")

    def no_network(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("test guard: no network", request=request)

    monkeypatch.setattr(socket, "getaddrinfo", no_resolver)
    monkeypatch.setattr(net_pin, "_build_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(no_network), follow_redirects=False, trust_env=False))


@pytest.fixture(autouse=True)
def no_proxy(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(net_pin, "getproxies", lambda: {})


@pytest.fixture(autouse=True)
def fresh_fake_ip_warnings(monkeypatch):
    """The delegation warnings are rate-limited per path in module state: every test starts
    with none logged, or one test's warning would silence the next test's."""
    monkeypatch.setattr(net_pin, "_delegation_warned", {})


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


@pytest.mark.parametrize("proxied", [False, True])
@pytest.mark.parametrize("host", ["localhost", "LOCALHOST.", "app.localhost", "printer.local",
                                  "nas.lan", "metadata.google.internal", "router.home.arpa",
                                  "wiki.intranet", "files.corp",
                                  # neither zone is delegated on the public internet
                                  "router.localdomain", "nas.home",
                                  # each zone itself, and a name with no dot at all
                                  "lan", "local", "internal", "intranet", "corp", "home.arpa",
                                  "localdomain", "home", "printer"])
async def test_local_names_are_refused_whatever_dns_says(monkeypatch, seen, host, proxied):
    if proxied:
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
            raise net_pin._BlockedHost(
                "html.duckduckgo.com resolves to a private or internal address")

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


# Leading zeros. macOS `getaddrinfo` reads `198.18.0.09` as 198.18.0.9, but `ipaddress` and
# `inet_aton` both refuse a `09` (not octal), so none of these was taken for an address. The
# connection is https-only and TLS-bounded, so it was never a way in; it did break the rule
# that an address, however it is spelled, is never a name. A host whose dot-separated labels
# are all numbers is an address, because no public name ends in a number (RFC 3696 section 2).

_LEADING_ZERO_SPELLINGS = ["198.18.0.09", "0198.18.0.33", "198.018.0.33"]


@pytest.mark.parametrize("proxied", [False, True])
@pytest.mark.parametrize("host", _LEADING_ZERO_SPELLINGS)
async def test_a_leading_zero_spelling_of_an_address_is_a_literal_not_a_name(monkeypatch, seen,
                                                                            host, proxied):
    """Fake answers and a fake canary, with and without a proxy: a name would pass here, so a
    refusal can only be the literal rule. It is the plain `_BlockedHost` of a literal judged by
    its address, neither `_FakeIpOnlyHttps` nor the local-name refusal."""
    with pytest.raises(ValueError):
        ipaddress.ip_address(host)                               # `ipaddress` does not parse it ...
    with pytest.raises(OSError):
        socket.inet_aton(host)                                   # ... and neither does `inet_aton`
    if proxied:
        _with_proxy(monkeypatch)
    _resolver(monkeypatch, {host: (FAKE,)}, default=(FAKE,))
    with pytest.raises(net_pin._BlockedHost) as caught:
        await net_pin.pinned_get(f"https://{host}/")
    assert type(caught.value) is net_pin._BlockedHost
    assert "private or internal address" in str(caught.value)
    assert not seen


@pytest.mark.parametrize("proxied", [False, True])
@pytest.mark.parametrize("host", ["123.example.com", "1password.com", "198.18.0.33.example.com",
                                  "0x7f.example.com"])
async def test_a_real_name_with_digits_in_it_is_still_a_name(monkeypatch, seen, host, proxied):
    """Only a host whose labels are ALL numbers is an address. A name with digits in a label,
    even the first four labels of an address, ends in a real top-level domain and is allowed
    behind fake-IP DNS exactly as before."""
    if proxied:
        _with_proxy(monkeypatch)
    _resolver(monkeypatch, {}, default=(FAKE,))
    resp = await net_pin.pinned_get(f"https://{host}/")
    assert resp.status_code == 200
    assert seen[0].url.host == (host if proxied else FAKE)   # proxy: the name; TUN: the stand-in


@pytest.mark.parametrize("host,expected", [
    # leading zeros: the spellings `ipaddress` and `inet_aton` refuse
    pytest.param("198.18.0.09", True, id="zero-in-last-label"),
    pytest.param("0198.18.0.33", True, id="zero-in-first-label"),
    pytest.param("198.018.0.33", True, id="zero-in-second-label"),
    # hex labels, one trailing dot
    pytest.param("0x7f.1", True, id="hex-and-decimal"),
    pytest.param("0X7F.0X1", True, id="upper-case-hex"),
    pytest.param("1.2.3.4.", True, id="one-trailing-dot"),
    pytest.param("1.2.3.4..", False, id="two-trailing-dots"),
    pytest.param("1..2", False, id="empty-label"),
    # the spellings the first two arms already read
    pytest.param("198.18.0.33", True, id="dotted-quad"),
    pytest.param("0xc6120021", True, id="bare-hex"),
    pytest.param("3323068449", True, id="bare-decimal"),
    pytest.param("::1", True, id="ipv6"),
    # names
    pytest.param("123.example.com", False, id="digits-then-a-real-tld"),
    pytest.param("1password.com", False, id="digit-leading-name"),
    pytest.param("a1.b2", False, id="letters-with-digits"),
    pytest.param("0xzz.1", False, id="not-hex"),
    pytest.param("", False, id="empty"),
])
def test_is_ip_literal_rows(host, expected):
    assert net_pin._is_ip_literal(host) is expected


# ── review round 1 ─────────────────────────────────────────────────────────────────
# CRITICAL 1: the guard judges the name the resolver and the HTTP stack really use.
# NFKC/IDNA turn fullwidth digits and letters, and the dots U+3002, U+FF0E and U+FF61, into
# ASCII AFTER the raw `urlparse` host was judged. A literal address or a local name in
# disguise was taken for a public NAME, and in fake-IP mode it was allowed.


@pytest.mark.parametrize("proxied", [False, True])
@pytest.mark.parametrize("host", [
    pytest.param("１２７.０.０.１", id="fullwidth-127.0.0.1"),
    pytest.param("１９８.１８.０.１", id="fullwidth-198.18.0.1"),
    pytest.param("198。18。0。1", id="ideographic-stops-198.18.0.1"),
    pytest.param("files。corp", id="ideographic-stop-files.corp"),
    # The other two dots IDNA reads as a label separator: U+FF0E FULLWIDTH FULL STOP and
    # U+FF61 HALFWIDTH IDEOGRAPHIC FULL STOP.
    pytest.param("198．18．0．1", id="fullwidth-stops-198.18.0.1"),
    pytest.param("files．corp", id="fullwidth-stop-files.corp"),
    pytest.param("198｡18｡0｡1", id="halfwidth-ideographic-stops-198.18.0.1"),
    pytest.param("files｡corp", id="halfwidth-ideographic-stop-files.corp"),
    pytest.param("metadata.google.ｉｎｔｅｒｎａｌ", id="fullwidth-metadata.google.internal"),
    pytest.param("nas.ｌａｎ", id="fullwidth-nas.lan"),
    # A name whose ONLY dots are ideographic looks dotless to a check on the raw spelling, so
    # the dotless rule alone would refuse the cases above. These keep an ASCII dot, and so
    # prove that it is the canonical form that refuses.
    pytest.param("198.18。0.1", id="mixed-stop-198.18.0.1"),
    pytest.param("www.files。corp", id="mixed-stop-www.files.corp"),
    pytest.param("198.18．0.1", id="mixed-fullwidth-stop-198.18.0.1"),
    pytest.param("www.files．corp", id="mixed-fullwidth-stop-www.files.corp"),
    pytest.param("198.18｡0.1", id="mixed-halfwidth-ideographic-stop-198.18.0.1"),
    pytest.param("www.files｡corp", id="mixed-halfwidth-ideographic-stop-www.files.corp"),
])
async def test_a_unicode_spelling_is_judged_in_its_canonical_form(monkeypatch, seen, host,
                                                                   proxied):
    """Each of these is the literal address or the local name it normalises to, so each is
    refused, with and without a proxy. httpx rejects some of them itself, so "nothing was
    sent" proves little: the GUARD has to be the one that says no."""
    if proxied:
        _with_proxy(monkeypatch)
    _resolver(monkeypatch, {}, default=(FAKE,))
    with pytest.raises(net_pin._BlockedHost):
        await net_pin.pinned_get(f"https://{host}/")
    assert not seen


# RULING (final review, R1): the exception is https:// on port 443 and nothing else, and never
# the TUN's own address. Plain http to a faked name is resolved again by the proxy or the TUN,
# which may route a LAN or loopback answer DIRECT: a card-free read of port-80 services on the
# LAN or on this Mac. TLS checked against the real name is what bounds the https case.

_FAKE_IP_ONLY_HTTPS = "behind fake-IP DNS only https:// on port 443 is fetched"


@pytest.mark.parametrize("proxied", [False, True])
@pytest.mark.parametrize("url", ["https://github.com:8443/", "https://github.com:5000/",
                                 "http://github.com:9090/"])
async def test_the_fake_exception_is_for_https_on_443_only(monkeypatch, seen, url, proxied):
    """AirPlay/ControlCenter (5000, 7000) and rapportd listen on every interface, the TUN's
    included: an odd port on a fake name could be a request to a service on this very Mac."""
    if proxied:
        _with_proxy(monkeypatch)
    _resolver(monkeypatch, {}, default=(FAKE,))
    with pytest.raises(net_pin._FakeIpOnlyHttps):
        await net_pin.pinned_get(url)
    assert not seen


@pytest.mark.parametrize("url", ["https://github.com/", "https://github.com:443/"])
async def test_a_fake_name_over_https_on_443_is_still_allowed(monkeypatch, seen, url):
    _resolver(monkeypatch, {}, default=(FAKE,))
    await net_pin.pinned_get(url)
    assert seen[0].url.host == FAKE


@pytest.mark.parametrize("proxied", [False, True])
@pytest.mark.parametrize("url", ["http://github.com/", "http://github.com:80/"])
async def test_a_fake_name_over_plain_http_is_refused(monkeypatch, seen, url, proxied):
    """Was allowed until the final review. Through a proxy, plain http is still pinned (no
    SNI), so the proxy is handed the fake address, maps it back to the name and resolves that
    itself: nothing proves who answers."""
    if proxied:
        _with_proxy(monkeypatch)
    _resolver(monkeypatch, {}, default=(FAKE,))
    with pytest.raises(net_pin._FakeIpOnlyHttps):
        await net_pin.pinned_get(url)
    assert not seen


def _fake_mode(monkeypatch, mode: str) -> bool:
    """The two ways a fake answer is vouched for. "tun": the system DNS is fake-IP (every name
    fake, the canary too). "via_proxy": a proxy resolves the name, and the canary answers
    public, so only `via_proxy` can be what lets it through. Returns `via_proxy`."""
    if mode == "tun":
        _resolver(monkeypatch, {}, default=(FAKE,))
        return False
    _resolver(monkeypatch, {"evil.test": (FAKE,)})
    return True


@pytest.mark.parametrize("mode", ["tun", "via_proxy"])
@pytest.mark.parametrize("url", ["http://evil.test/", "http://evil.test:443/",
                                 "https://evil.test:80/", "https://evil.test:8443/"])
def test_behind_fake_ip_dns_only_https_on_443_is_fetched(monkeypatch, url, mode):
    """Scheme AND port: http on 443 is not https, and https on 80 is not port 443."""
    via_proxy = _fake_mode(monkeypatch, mode)
    with pytest.raises(net_pin._FakeIpOnlyHttps) as caught:
        net_pin._resolve_pinned(url, via_proxy=via_proxy)
    assert net_pin.categorize(caught.value) == _FAKE_IP_ONLY_HTTPS


@pytest.mark.parametrize("mode", ["tun", "via_proxy"])
@pytest.mark.parametrize("url", ["https://evil.test/", "https://evil.test:443/"])
def test_https_on_443_behind_fake_ip_dns_is_still_allowed(monkeypatch, url, mode):
    """The effective port of https:// without one is 443."""
    via_proxy = _fake_mode(monkeypatch, mode)
    assert net_pin._resolve_pinned(url, via_proxy=via_proxy) == (FAKE, "evil.test", 443)


@pytest.mark.parametrize("mode", ["tun", "via_proxy"])
async def test_https_to_a_fake_name_is_fetched_in_both_modes(monkeypatch, seen, mode):
    if mode == "via_proxy":
        _with_proxy(monkeypatch)
    _fake_mode(monkeypatch, mode)
    await net_pin.pinned_get("https://evil.test/")
    # TUN: pinned to the stand-in the TUN maps back. Proxy: the proxy is given the name.
    assert seen[0].url.host == (FAKE if mode == "tun" else "evil.test")


@pytest.mark.parametrize("url", ["https://evil.test/", "http://evil.test/",
                                 "https://evil.test:8443/"])
async def test_fake_answers_on_an_ordinary_dns_are_a_private_address(monkeypatch, seen, url):
    """No proxy, and the canary answers public: this DNS is not fake-IP, so an answer in
    198.18.0.0/15 is a real, non-public address, refused as one, whatever the scheme. The
    canary is still asked for http, or this would wear the fake-IP label."""
    _resolver(monkeypatch, {"evil.test": (FAKE,)})
    with pytest.raises(net_pin._BlockedHost) as caught:
        await net_pin.pinned_get(url)
    assert type(caught.value) is net_pin._BlockedHost
    assert net_pin.categorize(caught.value) == "blocked address (local network)"
    assert not seen


@pytest.mark.parametrize("proxied", [False, True])
async def test_a_redirect_from_https_to_plain_http_on_a_fake_name_is_refused(monkeypatch,
                                                                           proxied):
    """The first hop is https on 443 and is allowed; its 302 to http:// is judged like any URL,
    and plain http to a faked name is refused."""
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(302, headers={"location": "http://evil.test/"})

    monkeypatch.setattr(net_pin, "_build_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False))
    if proxied:
        _with_proxy(monkeypatch)
    _resolver(monkeypatch, {}, default=(FAKE,))
    with pytest.raises(net_pin._FakeIpOnlyHttps):
        await net_pin._fetch_text("https://github.com/")
    assert len(sent) == 1                                   # only the first hop left the machine


@pytest.mark.parametrize("proxied", [False, True])
@pytest.mark.parametrize("answers", [(GATEWAY,), (GATEWAY, FAKE), (FAKE, GATEWAY)],
                         ids=["gateway", "gateway+fake", "fake+gateway"])
async def test_the_tun_gateway_is_never_a_names_fake_address(monkeypatch, seen, answers,
                                                             proxied):
    """Clash and mihomo keep 198.18.0.1 for the TUN itself and never hand it out for a name,
    and local services listen on it. A name that answers it is not a faked name."""
    if proxied:
        _with_proxy(monkeypatch)
    _resolver(monkeypatch, {"evil.test": answers}, default=(FAKE,))
    with pytest.raises(net_pin._BlockedHost):
        await net_pin.pinned_get("https://evil.test/")
    assert not seen


# MINOR 5: a name with no dot is local; allow_host keeps its exemption; an address is not a name.


async def test_a_configured_dotless_search_host_still_works(monkeypatch, seen):
    """A single-label name is local (the machine's search domains resolve it), but allow_host,
    typed by a human in Settings, keeps its exemption."""
    _resolver(monkeypatch, {"searx": ("192.168.1.20",)})
    await net_pin.pinned_get("http://searx/search", allow_host="searx")
    assert seen


async def test_a_public_ipv6_literal_is_not_taken_for_a_local_name(monkeypatch, seen):
    """It has no dot either, but it is an address, and a public one is fine."""
    _resolver(monkeypatch, {})
    await net_pin.pinned_get("https://[2606:4700:4700::1111]/")
    assert seen


# MINOR 6: the order of the lookups, and a redirect out of a fake name.


@pytest.mark.parametrize("proxied,expected", [(False, ["github.com", "example.com"]),
                                              (True, ["github.com"])])
async def test_the_lookup_order_in_fake_mode(monkeypatch, seen, proxied, expected):
    """TUN: the target, then the canary that proves the DNS is fake-IP. Behind a proxy the
    proxy resolves the name itself, so the canary is never asked."""
    if proxied:
        _with_proxy(monkeypatch)
    calls = _resolver(monkeypatch, {}, default=(FAKE,))
    await net_pin.pinned_get("https://github.com/")
    assert calls == expected


@pytest.mark.parametrize("proxied", [False, True])
@pytest.mark.parametrize("location", ["http://printer.local/", "http://192.168.1.10/",
                                      "http://127.0.0.1:9090/"])
async def test_a_redirect_from_a_fake_name_to_a_local_target_is_refused(monkeypatch, location,
                                                                       proxied):
    """The first hop is a fake name and is allowed; the 302 it answers is judged like any URL."""
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(302, headers={"location": location})

    monkeypatch.setattr(net_pin, "_build_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False))
    if proxied:
        _with_proxy(monkeypatch)
    _resolver(monkeypatch, {}, default=(FAKE,))
    with pytest.raises(net_pin._BlockedHost):
        await net_pin.pinned_get("https://github.com/")
    assert len(sent) == 1                                   # only the first hop left the machine


# IMPORTANT 2: a refusal says what it is. Unresolvable and not-the-configured-host are still
# refusals (callers catch `_BlockedHost`), but neither is "a blocked address on the local net".


@pytest.mark.parametrize("cls,message,expected", [
    ("_BlockedHost", "a.test resolves to a private or internal address",
     "blocked address (local network)"),
    ("_BlockedHost", "nas.lan is a local network name", "blocked address (local network)"),
    ("_Unresolvable", "cannot resolve a.test", "cannot resolve"),
    ("_NotConfiguredHost", "a.test is not the configured host (b.test)",
     "not the configured search host"),
    ("_FakeIpOnlyHttps", f"a.test: {_FAKE_IP_ONLY_HTTPS}", _FAKE_IP_ONLY_HTTPS),
    ("_InvalidHost", "'a\\x00.test' is not a host name: it holds a control character",
     "invalid host name"),
])
def test_each_refusal_is_named_for_what_it_is(cls, message, expected):
    assert net_pin.categorize(getattr(net_pin, cls)(message)) == expected


def test_the_named_refusals_are_still_blocked_hosts():
    """web_extract and browser_proxy catch `_BlockedHost`; the subclasses must be caught there."""
    for cls in (net_pin._Unresolvable, net_pin._NotConfiguredHost, net_pin._FakeIpOnlyHttps,
                net_pin._InvalidHost):
        assert issubclass(cls, net_pin._BlockedHost), cls


@pytest.mark.parametrize("failure", ["raises", "empty"])
async def test_an_unresolvable_name_raises_unresolvable(monkeypatch, seen, failure):
    def getaddrinfo(host, *a, **k):
        if failure == "raises":
            raise socket.gaierror("Name or service not known")
        return []

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    with pytest.raises(net_pin._Unresolvable):
        await net_pin.pinned_get("https://nothing.example/")
    assert not seen


@pytest.mark.parametrize("url", ["http://printer/", "https://other.example/"])
async def test_another_host_is_not_the_configured_host(monkeypatch, seen, url):
    """The allow_host check comes first: a dotless name is `not the configured host`, not
    `a local name`."""
    _resolver(monkeypatch, {})
    with pytest.raises(net_pin._NotConfiguredHost):
        await net_pin.pinned_get(url, allow_host="searx")
    assert not seen


# RULING (final review, R3): a host with a C0 control character or DEL in it is no name at all.
# `198.18.0.33\x00.example.com` passed as a NAME in fake-IP mode: `inet_aton` refuses the NUL,
# so it was no literal, and the C resolver stops reading at the NUL, so it resolves as the
# address 198.18.0.33. Refused before anything else is asked, a configured search host included.

_CONTROL_HOSTS = [pytest.param("198.18.0.33\x00.example.com", id="nul"),
                  pytest.param("evil\x1f.example.com", id="unit-separator"),
                  pytest.param("evil\x7f.example.com", id="del")]


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("allow", [None, "the-same-host", "another-host"])
@pytest.mark.parametrize("host", _CONTROL_HOSTS)
async def test_a_host_with_a_control_character_is_refused_first(monkeypatch, seen, host, allow,
                                                                scheme):
    """In TUN mode, where such a "name" would pass. `allow_host` equal to it does not exempt
    it, and a different one does not turn it into `not the configured host`: this check comes
    before that one, and before any lookup."""
    calls = _resolver(monkeypatch, {}, default=(FAKE,))
    allow_host = {"the-same-host": host, "another-host": "searx.lan"}.get(allow)
    with pytest.raises(net_pin._InvalidHost) as caught:
        await net_pin.pinned_get(f"{scheme}://{host}/", allow_host=allow_host)
    assert net_pin.categorize(caught.value) == "invalid host name"
    assert calls == []
    assert not seen


# web_extract names each refusal (it said "private or internal address" for all of them), and a
# name that does not resolve keeps the fetch-failed advice to try another source.


@pytest.mark.parametrize("url,expected", [
    pytest.param("https://nas.lan/", "url refused: blocked address (local network)",
                 id="local-name"),
    pytest.param("https://wiki.example/", "url refused: blocked address (local network)",
                 id="private-address"),
    pytest.param("http://evil.test/", f"url refused: {_FAKE_IP_ONLY_HTTPS}", id="fake-ip-http"),
    pytest.param("http://198.18.0.33\x00.example.com/", "url refused: invalid host name",
                 id="invalid-host"),
])
async def test_web_extract_names_each_refusal(monkeypatch, seen, url, expected):
    from server.registry import executors

    _resolver(monkeypatch, {"wiki.example": ("10.0.0.5",)}, default=(FAKE,))     # TUN mode
    out = await executors.WebExtractExecutor().execute({"url": url})
    assert out == {"ok": False, "error": expected}
    assert not seen


async def test_web_extract_says_a_dead_name_cannot_resolve(monkeypatch, seen):
    from server.registry import executors

    def getaddrinfo(host, *a, **k):
        raise socket.gaierror(8, "nodename nor servname provided, or not known")

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    out = await executors.WebExtractExecutor().execute({"url": "https://nothing.example/"})
    assert out["ok"] is False
    assert out["error"].startswith("fetch failed: cannot resolve — do not retry this URL; "
                                   "try another source")
    assert not seen


# IMPORTANT 3: the TUN path delegates, and says so. Final review: at most ONE warning per 10
# minutes for the whole path, not one per host. A hostile page can mint a fresh name for every
# request (the agent browser allows a great many), and one warning per name floods the log.
# Each name is still logged, at DEBUG, every time.

TUN_WARNING = ("fake-IP DNS: names resolve to stand-in addresses in 198.18.0.0/15 that the TUN "
               "maps back; the TUN decides where each request really goes, and SSRF protection "
               "for those names is delegated there (each name is logged at DEBUG)")
PROXY_WARNING = ("pinned_request: https via a configured proxy — address pinning is disabled "
                 "and SSRF protection is delegated to the proxy (each host is logged at DEBUG)")


def _logged(caplog, level: int, prefix: str) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.levelno == level and r.getMessage().startswith(prefix)]


def _tun_detail(host: str, ip: str = FAKE) -> str:
    return (f"fake-IP DNS: {host} → {ip}; the TUN maps it back and decides the real "
            "destination")


async def test_the_tun_path_says_that_protection_is_delegated(monkeypatch, seen, caplog):
    _resolver(monkeypatch, {}, default=(FAKE,))
    with caplog.at_level(logging.DEBUG, logger="server.registry.net_pin"):
        await net_pin.pinned_get("https://github.com/")
    assert _logged(caplog, logging.WARNING, "fake-IP DNS:") == [TUN_WARNING]
    assert _logged(caplog, logging.DEBUG, "fake-IP DNS:") == [_tun_detail("github.com")]


async def test_the_tun_warning_is_once_per_ten_minutes_for_the_whole_path(monkeypatch, seen,
                                                                         caplog):
    _resolver(monkeypatch, {}, default=(FAKE,))
    with caplog.at_level(logging.DEBUG, logger="server.registry.net_pin"):
        await net_pin.pinned_get("https://github.com/")
        await net_pin.pinned_get("https://pypi.org/")                  # another host: silent
        net_pin._delegation_warned["tun"] -= 601                       # ten minutes pass
        await net_pin.pinned_get("https://github.com/once-more")
    assert _logged(caplog, logging.WARNING, "fake-IP DNS:") == [TUN_WARNING, TUN_WARNING]
    assert _logged(caplog, logging.DEBUG, "fake-IP DNS:") == [
        _tun_detail("github.com"), _tun_detail("pypi.org"), _tun_detail("github.com")]


async def test_fifty_fresh_names_make_one_tun_warning(monkeypatch, seen, caplog):
    _resolver(monkeypatch, {}, default=(FAKE,))
    with caplog.at_level(logging.DEBUG, logger="server.registry.net_pin"):
        for i in range(50):
            await net_pin.pinned_get(f"https://n{i}.evil.test/")
    assert len(_logged(caplog, logging.WARNING, "fake-IP DNS:")) <= 1
    assert _logged(caplog, logging.DEBUG, "fake-IP DNS:") == [
        _tun_detail(f"n{i}.evil.test") for i in range(50)]


async def test_fifty_fresh_names_through_a_proxy_make_one_proxy_warning(monkeypatch, seen,
                                                                       caplog):
    """The proxy branch of pinned_request is reached on every https hop on a Mac with a system
    proxy, and it was not throttled at all."""
    _with_proxy(monkeypatch)
    _resolver(monkeypatch, {}, default=(FAKE,))
    with caplog.at_level(logging.DEBUG, logger="server.registry.net_pin"):
        for i in range(50):
            await net_pin.pinned_get(f"https://n{i}.evil.test/")
    assert _logged(caplog, logging.WARNING, "pinned_request:") == [PROXY_WARNING]
    assert _logged(caplog, logging.DEBUG, "pinned_request:") == [
        f"pinned_request: https via a configured proxy for n{i}.evil.test — the proxy "
        "resolves and connects" for i in range(50)]


async def test_the_two_paths_do_not_silence_each_other(monkeypatch, seen, caplog):
    with caplog.at_level(logging.WARNING, logger="server.registry.net_pin"):
        _resolver(monkeypatch, {}, default=(FAKE,))
        await net_pin.pinned_get("https://github.com/")                 # the TUN path
        _with_proxy(monkeypatch)
        await net_pin.pinned_get("https://pypi.org/")                   # the proxy path
    assert [r.getMessage() for r in caplog.records
            if r.name == "server.registry.net_pin"] == [TUN_WARNING, PROXY_WARNING]


async def test_the_detail_names_the_canonical_host(monkeypatch, seen, caplog):
    """One host spelled two ways is one host, and the DEBUG line is ASCII."""
    _resolver(monkeypatch, {}, default=(FAKE,))
    with caplog.at_level(logging.DEBUG, logger="server.registry.net_pin"):
        await net_pin.pinned_get("https://bücher.example/")
        await net_pin.pinned_get("https://ｂücher.example/")          # fullwidth b: same host
    assert _logged(caplog, logging.DEBUG, "fake-IP DNS:") == [
        _tun_detail("xn--bcher-kva.example")] * 2


def test_the_warning_memory_is_bounded():
    """A long-lived server meets many hosts; the table of what was warned about holds one key
    per path, however many hosts it meets."""
    for i in range(300):
        net_pin._warn_fake_ip(f"host{i}.example", FAKE)
    assert list(net_pin._delegation_warned) == ["tun"]


async def test_no_fake_ip_warning_for_ordinary_lookups_or_behind_a_proxy(monkeypatch, seen,
                                                                         caplog):
    """An ordinary lookup has nothing to say, and a proxied request already has its own
    warning (the proxy branch of pinned_request): this one is for the TUN path only."""
    with caplog.at_level(logging.DEBUG, logger="server.registry.net_pin"):
        _resolver(monkeypatch, {})                                 # public answers, public canary
        await net_pin.pinned_get("https://example.org/")
        _with_proxy(monkeypatch)
        _resolver(monkeypatch, {"github.com": (FAKE,)})            # fake answer, a proxy carries it
        await net_pin.pinned_get("https://github.com/")
    assert [r for r in caplog.records if r.getMessage().startswith("fake-IP DNS:")] == []
