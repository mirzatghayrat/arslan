"""allow_host: the one address the user typed may live on a private network.

WHY THIS IS SAFE TO ALLOW AT ALL. The model controls the QUERY, never the
destination — the destination is a string the user typed into Settings. So the
exemption widens the address class only while it simultaneously narrows the
destination to exactly one host.

🔴 WHAT THESE TESTS ARE FOR. "a LAN address can be reached" passes just as well
under a wrong implementation that made the exemption global. The assertions that
separate the designs are the ones about a DIFFERENT private host, a lookalike
prefix, and a redirect that leaves the allowed host — those are the three ways a
plausible-looking exemption leaks.
"""
from __future__ import annotations

import socket

import httpx
import pytest

from server.registry import net_pin

LAN = "192.168.1.10"
OTHER_LAN = "192.168.1.100"
PUBLIC = "93.184.216.34"


def _addrinfo(ip: str):
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(fam, socket.SOCK_STREAM, 6, "", (ip, 0))]


@pytest.fixture(autouse=True)
def no_env_proxy(monkeypatch):
    """🔴 A developer machine here really does export HTTPS_PROXY, and https+proxy
    legitimately disables pinning — without this the suite would exercise the
    DELEGATED path and report a pass for the wrong reason."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(net_pin, "getproxies", lambda: {})


@pytest.fixture(autouse=True)
def literal_dns(monkeypatch):
    """Answer every lookup with the host itself, so an IP literal resolves to itself
    and a name resolves to a public address."""
    def fake(host, *a, **k):
        try:
            return _addrinfo(str(host))
        except ValueError:
            return _addrinfo(PUBLIC)
    monkeypatch.setattr(socket, "getaddrinfo", fake)


def _client(monkeypatch, responses):
    seen: list[httpx.Request] = []
    it = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(it)

    monkeypatch.setattr(
        net_pin, "_build_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                  follow_redirects=False, trust_env=False))
    return seen


async def test_the_configured_lan_host_is_allowed(monkeypatch):
    _client(monkeypatch, [httpx.Response(200, json={"results": []})])
    resp = await net_pin.pinned_get(f"http://{LAN}:8080/search", allow_host=LAN)
    assert resp.status_code == 200


async def test_a_different_private_host_is_still_refused(monkeypatch):
    """The exemption belongs to one host, not to the category 'private'."""
    seen = _client(monkeypatch, [httpx.Response(200)])
    with pytest.raises(net_pin._BlockedHost):
        await net_pin.pinned_get(f"http://{OTHER_LAN}:8080/search", allow_host=LAN)
    assert not seen, "a refused request must not reach the transport"


async def test_a_lookalike_prefix_does_not_inherit_the_exemption(monkeypatch):
    """192.168.1.10 must not admit 192.168.1.100 — the check is equality, and a
    `startswith` would pass every other test in this file."""
    _client(monkeypatch, [httpx.Response(200)])
    with pytest.raises(net_pin._BlockedHost):
        await net_pin.pinned_get(f"http://{OTHER_LAN}/search", allow_host=LAN)


async def test_a_redirect_leaving_the_allowed_host_is_refused(monkeypatch):
    """A self-hosted instance told to 302 elsewhere is the whole attack. Refused even
    though the target is public — this destination is pinned to one host, and
    "somewhere else, but reputable" is not the same thing as "where the user said"."""
    seen = _client(monkeypatch, [
        httpx.Response(302, headers={"location": "https://evil.test/steal"}),
        httpx.Response(200, json={"results": []}),
    ])
    with pytest.raises(net_pin._BlockedHost):
        await net_pin.pinned_get(f"http://{LAN}:8080/search", allow_host=LAN)
    assert len(seen) == 1, "the second hop must never be sent"


async def test_a_redirect_within_the_allowed_host_is_followed(monkeypatch):
    """The other side: staying on the configured host is normal and must work, or the
    refusal above would just be 'redirects are broken'."""
    seen = _client(monkeypatch, [
        httpx.Response(302, headers={"location": f"http://{LAN}:8080/search?p=2"}),
        httpx.Response(200, json={"results": []}),
    ])
    resp = await net_pin.pinned_get(f"http://{LAN}:8080/search", allow_host=LAN)
    assert resp.status_code == 200
    assert len(seen) == 2


async def test_without_allow_host_a_private_address_is_still_refused(monkeypatch):
    """Regression for every caller that does not pass it — web_extract, Tavily, the
    DuckDuckGo fallback. The exemption must not be reachable by omission."""
    _client(monkeypatch, [httpx.Response(200)])
    with pytest.raises(net_pin._BlockedHost):
        await net_pin.pinned_get(f"http://{LAN}:8080/search")


async def test_allow_host_also_narrows_a_public_destination(monkeypatch):
    """allow_host is not only a widening. Pointing it at one host means every other
    host is refused, public ones included."""
    _client(monkeypatch, [httpx.Response(200)])
    with pytest.raises(net_pin._BlockedHost):
        await net_pin.pinned_get("https://example.test/search", allow_host=LAN)


async def test_the_exemption_is_not_sticky_across_calls(monkeypatch):
    """🔴 The implementation constraint, asserted rather than trusted: the exemption
    is threaded per call. If it were ever stored on the module — a flag, a
    contextvar, a cached client — this second call would inherit it, and
    web_extract would quietly gain LAN access after any search."""
    _client(monkeypatch, [httpx.Response(200, json={"results": []})])
    await net_pin.pinned_get(f"http://{LAN}:8080/search", allow_host=LAN)

    _client(monkeypatch, [httpx.Response(200)])
    with pytest.raises(net_pin._BlockedHost):
        await net_pin.pinned_get(f"http://{LAN}:8080/search")
