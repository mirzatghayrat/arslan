"""FU-1: DNS rebinding on the web_extract / ingest_url fetch path.

THE BUG. `_is_private_host(url)` resolved the hostname and judged it, then `_fetch_text`
handed the HOSTNAME to httpx, which resolved it AGAIN before connecting. Nothing bound
the checked answer to the used one, so an attacker serving TTL=0 DNS returns a public IP
for the check and 127.0.0.1 for the connect. The redirect hardening from an earlier round
(per-hop `_is_private_host`) does not touch this: every hop had the same split.

THE TEST THAT MATTERS. Asserting "a private hostname is refused" passes on the OLD code
too — it is the check that already worked. The only assertion that separates the designs
is WHICH ADDRESS WAS ACTUALLY CONNECTED TO, with a resolver that changes its answer
between the two lookups. So these tests drive a fake resolver whose FIRST answer is
public and whose SECOND is private, and assert the request went to the pinned public IP.
"""
from __future__ import annotations

import socket

import httpx
import pytest

from server.registry import executors
from server.registry import net_pin

PUBLIC = "93.184.216.34"
PRIVATE = "127.0.0.1"


def _addrinfo(ip: str):
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(fam, socket.SOCK_STREAM, 6, "", (ip, 0))]


@pytest.fixture(autouse=True)
def no_env_proxy(monkeypatch):
    """🔴 Clear proxy env for every test in this file. A developer machine in this
    project really does export HTTPS_PROXY, and https+proxy legitimately disables
    pinning — so without this the suite would silently exercise the DELEGATED path and
    report the pinning tests as failures (or, worse, as passes for the wrong reason)."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(net_pin, "getproxies", lambda: {})


@pytest.fixture
def rebinding(monkeypatch):
    """A resolver that answers PUBLIC once, then PRIVATE forever after — the DNS an
    attacker controls. Records how many times it was asked."""
    calls: list[str] = []

    def fake(host, *a, **k):
        calls.append(host)
        return _addrinfo(PUBLIC if len(calls) == 1 else PRIVATE)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return calls


@pytest.fixture
def capture(monkeypatch):
    """Replace the transport so nothing leaves the machine, and record the request the
    client actually built — the pinned IP has to be visible IN the request."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="<html><body>" + "hello world. " * 20 + "</body></html>")

    # Build the client with transport= (supported) rather than poking `_transport`:
    # httpx resolves `_mounts` BEFORE `_transport`, so with an env proxy configured the
    # private-attribute trick silently sends a REAL request. trust_env=False keeps the
    # test hermetic for the same reason.
    monkeypatch.setattr(
        net_pin, "_build_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                  follow_redirects=False, trust_env=False))
    return seen


# ── the discriminating test ────────────────────────────────────────────────────────


async def test_connection_uses_the_pinned_address_not_a_second_lookup(rebinding, capture):
    """🔴 The whole point. Under the old code the hostname reached the transport and the
    second (private) answer would have been used; here the request must carry the FIRST,
    validated address."""
    res = await executors.EXECUTORS["web_extract"].execute({"url": "https://evil.test/page"})
    assert res.get("ok"), res

    assert len(capture) == 1
    req = capture[0]
    assert req.url.host == PUBLIC, (
        f"connected to {req.url.host!r} — the request must go to the address that was "
        "validated, not to whatever DNS says at connect time")
    assert req.url.host != PRIVATE


async def test_pinning_keeps_certificate_validation_on_the_REAL_hostname(rebinding, capture):
    """Pinning the IP must not weaken TLS. The Host header carries the original name and
    `sni_hostname` drives the handshake, so the certificate is still checked against
    evil.test — not against the IP, which would accept any cert the attacker holds."""
    await executors.EXECUTORS["web_extract"].execute({"url": "https://evil.test/page"})
    req = capture[0]
    assert req.headers["Host"].startswith("evil.test")
    assert req.extensions.get("sni_hostname") == "evil.test"


async def test_a_redirect_hop_is_pinned_too(monkeypatch, capture):
    """Each hop resolves once and is pinned. A hop that re-resolved would reopen exactly
    the same hole one level down."""
    calls: list[str] = []

    def fake(host, *a, **k):
        calls.append(host)
        # first host: public then private; second host: public then private
        first_for_host = calls.count(host) == 1
        return _addrinfo(PUBLIC if first_for_host else PRIVATE)

    monkeypatch.setattr(socket, "getaddrinfo", fake)

    hops: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hops.append(request)
        if len(hops) == 1:
            return httpx.Response(302, headers={"location": "https://second.test/next"})
        return httpx.Response(200, text="<html><body>" + "landed here. " * 20 + "</body></html>")

    monkeypatch.setattr(
        net_pin, "_build_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                  follow_redirects=False, trust_env=False))

    res = await executors.EXECUTORS["web_extract"].execute({"url": "https://first.test/a"})
    assert res.get("ok"), res
    assert len(hops) == 2
    assert hops[1].url.host == PUBLIC
    assert hops[1].headers["Host"].startswith("second.test")


# ── regressions: the guard that already worked must keep working ──────────────────


async def test_a_private_only_answer_is_refused(monkeypatch, capture):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(PRIVATE))
    res = await executors.EXECUTORS["web_extract"].execute({"url": "http://intranet.test/"})
    assert not res.get("ok")
    assert "private" in res["error"]
    assert capture == [], "nothing may be sent when the host is refused"


async def test_ANY_private_answer_refuses_even_when_another_is_public(monkeypatch, capture):
    """Multi-answer DNS: picking 'the first public one' out of a mixed set would let an
    attacker pad the answer with a public IP to get past the check."""
    def fake(*a, **k):
        return _addrinfo(PUBLIC) + _addrinfo(PRIVATE)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    res = await executors.EXECUTORS["web_extract"].execute({"url": "http://mixed.test/"})
    assert not res.get("ok")
    assert capture == []


async def test_unresolvable_is_refused(monkeypatch, capture):
    def boom(*a, **k):
        raise OSError("NXDOMAIN")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    res = await executors.EXECUTORS["web_extract"].execute({"url": "http://nope.test/"})
    assert not res.get("ok")
    assert capture == []


async def test_a_redirect_to_a_private_host_is_refused(monkeypatch):
    calls: list[str] = []

    def fake(host, *a, **k):
        calls.append(host)
        return _addrinfo(PUBLIC if host == "ok.test" else PRIVATE)

    monkeypatch.setattr(socket, "getaddrinfo", fake)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://intranet.test/secret"})

    monkeypatch.setattr(
        net_pin, "_build_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                  follow_redirects=False, trust_env=False))

    res = await executors.EXECUTORS["web_extract"].execute({"url": "http://ok.test/a"})
    assert not res.get("ok")



# ── the address predicate itself ───────────────────────────────────────────────────
#
# 🔴 These are driven THROUGH the executor, not against the predicate, because the whole
# failure mode here was a predicate that looked right in isolation. The four-way
# `is_private or is_loopback or is_link_local or is_reserved` check that shipped for
# months admits RFC 6598 (100.64.0.0/10) — CGNAT, and the entirety of a Tailscale
# tailnet. No rebinding needed: a static A record was enough.


@pytest.mark.parametrize("addr", [
    "100.64.1.1",          # RFC 6598 CGNAT / Tailscale tailnet — the one that got through
    "100.127.255.254",     # far end of the same /10
    "127.0.0.1",           # loopback
    "10.0.0.5",            # RFC 1918
    "192.168.1.1",         # RFC 1918
    "169.254.169.254",     # cloud metadata
    "0.0.0.0",             # unspecified
    "198.18.0.1",          # benchmarking
    "224.0.0.1",           # multicast
    "::ffff:127.0.0.1",    # IPv4-mapped loopback
    "fc00::1",             # IPv6 ULA
    "ff02::1",             # IPv6 multicast
])
async def test_non_public_addresses_are_refused(monkeypatch, capture, addr):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(addr))
    res = await executors.EXECUTORS["web_extract"].execute({"url": "http://attacker.test/x"})
    assert not res.get("ok"), f"{addr} was FETCHED — it must be refused"
    assert capture == [], f"a request was sent to {addr}"


@pytest.mark.parametrize("addr", ["93.184.216.34", "8.8.8.8", "1.1.1.1",
                                  "2606:4700:4700::1111"])
async def test_public_addresses_still_work(monkeypatch, capture, addr):
    """The allow-list must not be so tight that the tool stops working."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(addr))
    res = await executors.EXECUTORS["web_extract"].execute({"url": "http://ok.test/x"})
    assert res.get("ok"), res


# ── proxy interaction ──────────────────────────────────────────────────────────────


async def test_https_through_a_proxy_degrades_LOUDLY_not_silently(monkeypatch, capture, caplog):
    """The one cell where pinning cannot work. It must still validate, must not mangle
    the URL (that is what breaks TLS through a CONNECT tunnel), and must SAY so."""
    monkeypatch.setattr(net_pin, "getproxies",
                        lambda: {"https": "http://127.0.0.1:7899"})
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(PUBLIC))

    with caplog.at_level("WARNING"):
        res = await executors.EXECUTORS["web_extract"].execute({"url": "https://ok.test/x"})
    assert res.get("ok"), res
    assert capture[0].url.host == "ok.test", (
        "under a proxy the ORIGINAL host must be sent — rewriting it to the IP is what "
        "breaks certificate validation on the tunnel path")
    assert any("delegated to the proxy" in r.message for r in caplog.records)


async def test_a_proxy_does_not_disable_the_address_check(monkeypatch, capture):
    monkeypatch.setattr(net_pin, "getproxies",
                        lambda: {"https": "http://127.0.0.1:7899"})
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("127.0.0.1"))
    res = await executors.EXECUTORS["web_extract"].execute({"url": "https://evil.test/x"})
    assert not res.get("ok")
    assert capture == []


async def test_plain_http_through_a_proxy_still_pins(monkeypatch, capture):
    """Only https+proxy degrades. HTTP has no SNI, and a proxy honours the address in an
    absolute-form request line, so the pin survives."""
    monkeypatch.setattr(net_pin, "getproxies",
                        lambda: {"http": "http://127.0.0.1:7899"})
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(PUBLIC))
    res = await executors.EXECUTORS["web_extract"].execute({"url": "http://ok.test/x"})
    assert res.get("ok"), res
    assert capture[0].url.host == PUBLIC
