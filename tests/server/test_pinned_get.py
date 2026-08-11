"""pinned_get is the public entry to the pinned fetch path web_extract already uses.

WHAT THESE ASSERT, and why it is not the obvious thing. "a private hostname is
refused" passes both before and after this extraction — it is the check that already
worked, so it cannot tell the two designs apart. What separates them is WHICH ADDRESS
THE REQUEST ACTUALLY WENT TO, so these tests drive a fake resolver and read the address
off the request the client built (the same discriminator as
test_ssrf_dns_rebinding.py, for the same reason).
"""
from __future__ import annotations

import socket

import httpx
import pytest

from server.registry import net_pin

PUBLIC = "93.184.216.34"
PRIVATE = "127.0.0.1"


def _addrinfo(ip: str):
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(fam, socket.SOCK_STREAM, 6, "", (ip, 0))]


@pytest.fixture(autouse=True)
def no_env_proxy(monkeypatch):
    """🔴 A developer machine in this project really does export HTTPS_PROXY, and
    https+proxy legitimately disables pinning — so without this the suite would
    exercise the DELEGATED path and report the result as a pass for the wrong reason."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(net_pin, "getproxies", lambda: {})


@pytest.fixture
def capture(monkeypatch):
    """Replace the transport so nothing leaves the machine, and record what was built."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(
        net_pin, "_build_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                  follow_redirects=False, trust_env=False))
    return seen


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(PUBLIC))


async def test_request_goes_to_the_validated_address(public_dns, capture):
    resp = await net_pin.pinned_get("https://example.test/search")
    assert resp.status_code == 200
    assert capture[0].url.host == PUBLIC, (
        "the request must go to the address that was validated, not to whatever DNS "
        "says at connect time")


async def test_tls_still_verifies_the_real_hostname(public_dns, capture):
    """Pinning the IP must not weaken TLS: the certificate is still checked against
    the real name, not against whatever cert the address happens to present."""
    await net_pin.pinned_get("https://example.test/search")
    req = capture[0]
    assert req.headers["Host"].startswith("example.test")
    assert req.extensions.get("sni_hostname") == "example.test"


async def test_params_and_headers_survive_pinning(public_dns, capture):
    await net_pin.pinned_get("https://example.test/search",
                             params={"q": "hello", "format": "json"},
                             headers={"Accept": "application/json"})
    req = capture[0]
    assert req.url.params["q"] == "hello"
    assert req.url.params["format"] == "json"
    assert req.headers["Accept"] == "application/json"
    assert req.headers["Host"].startswith("example.test"), (
        "caller headers must not clobber the Host header pinning depends on")


async def test_a_private_address_is_refused_without_allow_host(capture, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(PRIVATE))
    with pytest.raises(net_pin._BlockedHost):
        await net_pin.pinned_get("http://192.168.1.10:8080/search")
    assert not capture, "a refused request must not reach the transport at all"


async def test_status_is_returned_not_raised(public_dns, monkeypatch):
    """The connection test needs to read the status itself, so this helper does not
    call raise_for_status() on the caller's behalf."""
    monkeypatch.setattr(
        net_pin, "_build_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(404, text="nope")),
            follow_redirects=False, trust_env=False))
    resp = await net_pin.pinned_get("https://example.test/search")
    assert resp.status_code == 404


async def test_a_redirect_hop_is_pinned_too(monkeypatch):
    """Each hop resolves once and is pinned. A hop that re-resolved would reopen the
    same hole one level down."""
    answers = iter([PUBLIC, PUBLIC])

    def fake(host, *a, **k):
        return _addrinfo(next(answers, PUBLIC))

    monkeypatch.setattr(socket, "getaddrinfo", fake)

    seen: list[httpx.Request] = []
    responses = iter([
        httpx.Response(302, headers={"location": "https://example.test/second"}),
        httpx.Response(200, json={"results": []}),
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(responses)

    monkeypatch.setattr(
        net_pin, "_build_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                  follow_redirects=False, trust_env=False))

    resp = await net_pin.pinned_get("https://example.test/first")
    assert resp.status_code == 200
    assert len(seen) == 2
    assert all(r.url.host == PUBLIC for r in seen), (
        "every hop must go to a validated, pinned address")
