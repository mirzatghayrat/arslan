"""POST through the pinned path, including what a redirect does to the method.

WHY THIS EXISTS. Both search providers POST — Tavily sends JSON, the DuckDuckGo
fallback sends a form — so routing search through the pinned path means the path
has to carry a method and a body, not just a URL.

🔴 THE PART THAT IS EASY TO GET WRONG. httpx's own `follow_redirects` applies the
RFC method-change rules; a hand-rolled loop that ignores them either replays a POST
body somewhere it should not, or silently drops the body and sends a bodyless POST
that the server answers with an error nobody can explain. Since the loop here is
hand-rolled on purpose (so every hop can be re-pinned), the rules are asserted
rather than assumed.
"""
from __future__ import annotations

import socket

import httpx
import pytest

from server.registry import net_pin

PUBLIC = "93.184.216.34"


def _addrinfo(ip: str):
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(fam, socket.SOCK_STREAM, 6, "", (ip, 0))]


@pytest.fixture(autouse=True)
def no_env_proxy(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(net_pin, "getproxies", lambda: {})


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(PUBLIC))


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


async def test_a_json_post_reaches_the_pinned_address_with_its_body(monkeypatch):
    seen = _client(monkeypatch, [httpx.Response(200, json={"results": []})])
    await net_pin.pinned_request("POST", "https://api.example.test/search",
                                 json={"query": "hello", "max_results": 5})
    req = seen[0]
    assert req.method == "POST"
    assert req.url.host == PUBLIC
    assert b'"query"' in req.content and b"hello" in req.content


async def test_a_form_post_reaches_the_pinned_address_with_its_body(monkeypatch):
    seen = _client(monkeypatch, [httpx.Response(200, text="<html></html>")])
    await net_pin.pinned_request("POST", "https://html.example.test/html/",
                                 data={"q": "hello"}, headers={"User-Agent": "x"})
    req = seen[0]
    assert req.method == "POST"
    assert b"q=hello" in req.content
    assert req.headers["User-Agent"] == "x"


async def test_a_302_turns_a_post_into_a_bodyless_get(monkeypatch):
    """RFC 9110 / universal browser behaviour. Replaying the body would re-submit a
    write to a destination that only asked us to look somewhere else."""
    seen = _client(monkeypatch, [
        httpx.Response(302, headers={"location": "https://example.test/landed"}),
        httpx.Response(200, text="ok"),
    ])
    await net_pin.pinned_request("POST", "https://example.test/start",
                                 data={"q": "hello"})
    assert [r.method for r in seen] == ["POST", "GET"]
    assert seen[1].content == b"", "the body must not be replayed onto the GET"


async def test_a_307_preserves_the_method_and_the_body(monkeypatch):
    """307 exists precisely to say 'same request, new address'."""
    seen = _client(monkeypatch, [
        httpx.Response(307, headers={"location": "https://example.test/landed"}),
        httpx.Response(200, text="ok"),
    ])
    await net_pin.pinned_request("POST", "https://example.test/start",
                                 data={"q": "hello"})
    assert [r.method for r in seen] == ["POST", "POST"]
    assert b"q=hello" in seen[1].content


async def test_a_303_becomes_a_get_even_from_a_get(monkeypatch):
    seen = _client(monkeypatch, [
        httpx.Response(303, headers={"location": "https://example.test/landed"}),
        httpx.Response(200, text="ok"),
    ])
    await net_pin.pinned_request("POST", "https://example.test/start",
                                 json={"a": 1})
    assert [r.method for r in seen] == ["POST", "GET"]


async def test_every_hop_of_a_post_redirect_is_still_pinned(monkeypatch):
    """The method rules must not cost the property the loop exists for."""
    seen = _client(monkeypatch, [
        httpx.Response(302, headers={"location": "https://elsewhere.test/landed"}),
        httpx.Response(200, text="ok"),
    ])
    await net_pin.pinned_request("POST", "https://example.test/start",
                                 data={"q": "hello"})
    assert all(r.url.host == PUBLIC for r in seen)
    assert seen[1].headers["Host"].startswith("elsewhere.test"), (
        "the second hop must be pinned against ITS OWN hostname, not the first's")


async def test_pinned_get_is_the_same_path(monkeypatch):
    """`pinned_get` stays as the readable spelling for the common case; it must not
    become a second implementation."""
    seen = _client(monkeypatch, [httpx.Response(200, text="ok")])
    await net_pin.pinned_get("https://example.test/page")
    assert seen[0].method == "GET"
    assert seen[0].url.host == PUBLIC
