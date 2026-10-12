"""The suite-wide network guard: ``_no_real_network_off_loopback`` in tests/conftest.py.

WHY IT EXISTS. Hermeticity used to hold only for a CORRECT implementation. A test of the web tools
replaced the resolver and the transport with fakes, and code that went AROUND a fake (a mutant, or
a regression) reached this Mac's real system proxy (127.0.0.1:7899, which forwards to the
internet) and its real, fake-IP DNS. A review mutation run sent about 250 real GETs that way
before it was caught. The guard makes that impossible from outside any single test file: it holds
whatever a test patches or forgets to patch.

WHAT IT REFUSES, for every test:
 - ``socket.getaddrinfo`` of anything that is not loopback, a literal address included;
 - a request by a REAL httpx transport (``httpx.AsyncHTTPTransport`` / ``httpx.HTTPTransport``) to a
   host that is not loopback;
 - a request by a real httpx transport that goes through a PROXY, a loopback one included: the
   system proxy listens on 127.0.0.1, so "loopback only" let a real client through to it. (A fully
   socket-level "loopback only to ports this process listens on" rule would also refuse the tests
   that talk to a server started in a subprocess, e.g. test_profile_activation.)
``httpx.MockTransport`` and ``httpx.ASGITransport`` are not real transports and are untouched. A
test that needs a resolver patches its own, which wins while it is active; the guard is installed in
its own ``pytest.MonkeyPatch.context()``, so a test's ``monkeypatch.undo()`` cannot lift it.

These tests aim only at addresses that are safe even if the guard were broken: ``.invalid`` names
(RFC 6761, never delegated), 192.0.2.1 and 2001:db8::1 (RFC 5737 / 3849 documentation addresses,
never routed), loopback ports that nothing listens on. The ``no_connect`` fixture also refuses and
records any real ``connect``, so a broken guard fails these tests without putting anything on a
wire.
"""
from __future__ import annotations

import asyncio
import socket

import httpx
import pytest


@pytest.fixture
def no_connect(monkeypatch):
    """Refuse (and record) any real ``connect``: a guard that fails must not reach a wire."""
    attempts: list[object] = []

    def refuse(self, address):
        attempts.append(address)
        raise OSError("self-test: a real connect was refused here")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    return attempts


@pytest.fixture
def own_resolver(monkeypatch):
    """A test's own resolver, which answers: the lookup guard then cannot be the one that refuses,
    and the transport guard has to refuse on its own (the sync transport resolves even literals)."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", port))])


@pytest.mark.parametrize("host", ["guard-selftest.invalid", b"guard-selftest.invalid",
                                  "192.0.2.1", "2001:db8::1"])
def test_a_lookup_off_loopback_is_refused(host):
    with pytest.raises(socket.gaierror, match="test guard"):
        socket.getaddrinfo(host, 443)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", b"127.0.0.1", None])
def test_a_loopback_lookup_still_works(host):
    flags = socket.AI_PASSIVE if host is None else 0
    assert socket.getaddrinfo(host, 80, flags=flags)


def test_a_tests_own_resolver_patch_wins_and_the_guard_comes_back(monkeypatch):
    """The guard is under the test's patch, not instead of it: its own resolver answers while it is
    in place, and `undo()` returns to the GUARD, not to the real resolver."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [("sentinel",)])
    assert socket.getaddrinfo("guard-selftest.invalid", 80) == [("sentinel",)]
    monkeypatch.undo()
    with pytest.raises(socket.gaierror, match="test guard"):
        socket.getaddrinfo("guard-selftest.invalid", 80)


async def test_a_real_async_transport_is_refused_off_loopback(own_resolver, no_connect):
    async with httpx.AsyncClient(trust_env=False, timeout=1) as client:
        with pytest.raises(httpx.ConnectError, match="test guard"):
            await client.get("http://192.0.2.1/")
    assert no_connect == []


def test_a_real_sync_transport_is_refused_off_loopback(own_resolver, no_connect):
    with httpx.Client(trust_env=False, timeout=1) as client:
        with pytest.raises(httpx.ConnectError, match="test guard"):
            client.get("http://192.0.2.1/")
    assert no_connect == []


@pytest.mark.parametrize("how", ["explicit", "from-env"])
async def test_a_real_async_transport_through_a_proxy_is_refused_even_to_loopback(
        monkeypatch, no_connect, how):
    """The path the Mac's own proxy takes: the target is loopback, the hop is the proxy."""
    if how == "explicit":
        client = httpx.AsyncClient(proxy="http://127.0.0.1:9", trust_env=False, timeout=1)
    else:
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        client = httpx.AsyncClient(timeout=1)
    async with client:
        with pytest.raises(httpx.ConnectError, match="test guard"):
            await client.get("http://127.0.0.1:1/")
    assert no_connect == []


def test_a_real_sync_transport_through_a_proxy_is_refused_even_to_loopback(no_connect):
    with httpx.Client(proxy="http://127.0.0.1:9", trust_env=False, timeout=1) as client:
        with pytest.raises(httpx.ConnectError, match="test guard"):
            client.get("http://127.0.0.1:1/")
    assert no_connect == []


async def test_a_real_client_still_reaches_a_server_in_this_process():
    """The guard is not a wall around loopback: the tests that serve from this process need it."""
    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            assert (await client.get(f"http://127.0.0.1:{port}/")).text == "ok"
    finally:
        server.close()
        await server.wait_closed()


async def test_mock_and_asgi_transports_are_untouched():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"asgi"})

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://example.com") as client:
        assert (await client.get("/")).text == "asgi"
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="mock"))) as client:
        assert (await client.get("http://example.com/")).text == "mock"
