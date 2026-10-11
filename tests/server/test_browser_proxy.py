import asyncio
import socket

import pytest

from server.registry import net_pin
from server.services import browser_proxy as bp


@pytest.fixture(autouse=True)
def no_system_proxy(monkeypatch):
    """The developer Mac has a system proxy (127.0.0.1:7899); without this the tunnel
    would chain through it and the existing tests would dial a real proxy."""
    monkeypatch.setattr(net_pin, "getproxies", lambda: {})


@pytest.mark.parametrize("url", ["http://example.com", "file:///etc/passwd", "https://u:p@example.com",
                                     "https://example.com:444", "https://example.com/\nfoo",
                                     "https://example.com\\@127.0.0.1", "https://[broken"])
def test_preview_url_refuses_unsafe_shapes(url):
    with pytest.raises(ValueError):
        bp.validate_url(url)


async def _request(port, target):
    read, write = await asyncio.open_connection("127.0.0.1", port)
    write.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
    await write.drain()
    reply = await read.readuntil(b"\r\n\r\n")
    write.close()
    await write.wait_closed()
    return reply


@pytest.mark.asyncio
async def test_proxy_refuses_loopback_and_non_https():
    async with bp.PublicTunnel() as proxy:
        assert b"403" in await _request(proxy.port, "127.0.0.1:443")
        assert b"403" in await _request(proxy.port, "example.com:80")
    assert proxy.blocked == 2
    assert not proxy.tasks


@pytest.mark.asyncio
async def test_proxy_connects_to_validated_ip_not_dns_name(monkeypatch):
    original_connect = asyncio.open_connection
    connected = []

    async def echo(reader, writer):
        try:
            writer.write(await reader.read(100))
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(echo, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async def pinned_connect(host, requested_port):
        connected.append((host, requested_port))
        return await original_connect("127.0.0.1", port)

    monkeypatch.setattr(bp, "_resolve_pinned", lambda _: ("93.184.216.34", "example.com", 443))
    async with bp.PublicTunnel() as proxy:
        reader, writer = await original_connect("127.0.0.1", proxy.port)
        monkeypatch.setattr(bp.asyncio, "open_connection", pinned_connect)
        writer.write(b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
        await writer.drain()
        assert b"200" in await reader.readuntil(b"\r\n\r\n")
        writer.write(b"opaque TLS bytes")
        await writer.drain()
        assert await reader.readexactly(16) == b"opaque TLS bytes"
        writer.close()
        await writer.wait_closed()
    server.close()
    await server.wait_closed()
    assert connected == [("93.184.216.34", 443)]


@pytest.mark.asyncio
async def test_proxy_admission_budget_fails_closed():
    async with bp.PublicTunnel(connection_limit=0) as proxy:
        assert b"403" in await _request(proxy.port, "example.com:443")
    assert proxy.blocked == 1


_REAL_GETADDRINFO = socket.getaddrinfo


def _answers(monkeypatch, table: dict[str, str]):
    def fake(host, *a, **k):
        if host in table:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], 0))]
        return _REAL_GETADDRINFO(host, *a, **k)
    monkeypatch.setattr(socket, "getaddrinfo", fake)


def _system_proxy(monkeypatch, port: int, scheme: str = "http"):
    monkeypatch.setattr(net_pin, "getproxies", lambda: {"https": f"{scheme}://127.0.0.1:{port}"})
    monkeypatch.setattr(net_pin, "proxy_bypass", lambda host: False)


async def _upstream(record: list, reply: bytes = b"HTTP/1.1 200 Connection established\r\n\r\n"):
    """A stand-in for the user's proxy: records the CONNECT it got, answers `reply`, and on
    200 echoes the first tunnelled bytes back."""
    async def handle(reader, writer):
        try:
            record.append(await reader.readuntil(b"\r\n\r\n"))
            writer.write(reply)
            await writer.drain()
            if reply.startswith(b"HTTP/1.1 200"):
                writer.write(await reader.read(100))
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


@pytest.mark.asyncio
async def test_tunnel_chains_through_the_system_proxy_by_name(monkeypatch):
    record: list[bytes] = []
    server, port = await _upstream(record)
    _system_proxy(monkeypatch, port)
    _answers(monkeypatch, {"duckduckgo.com": "198.18.0.35"})     # fake-IP DNS
    async with bp.PublicTunnel() as proxy:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
        writer.write(b"CONNECT duckduckgo.com:443 HTTP/1.1\r\n\r\n")
        await writer.drain()
        assert b"200" in await reader.readuntil(b"\r\n\r\n")
        writer.write(b"opaque TLS bytes")
        await writer.drain()
        assert await reader.readexactly(16) == b"opaque TLS bytes"
        writer.close()
        await writer.wait_closed()
    server.close()
    await server.wait_closed()
    assert record and record[0].startswith(b"CONNECT duckduckgo.com:443 HTTP/1.1\r\n")


@pytest.mark.asyncio
async def test_tunnel_refuses_a_private_name_even_with_a_proxy(monkeypatch):
    record: list[bytes] = []
    server, port = await _upstream(record)
    _system_proxy(monkeypatch, port)
    _answers(monkeypatch, {"wiki.example": "10.0.0.5"})
    async with bp.PublicTunnel() as proxy:
        assert b"403" in await _request(proxy.port, "wiki.example:443")
    server.close()
    await server.wait_closed()
    assert record == []                 # the upstream proxy was never asked
    assert proxy.blocked == 1


@pytest.mark.asyncio
async def test_tunnel_reports_an_upstream_refusal_as_blocked(monkeypatch):
    record: list[bytes] = []
    server, port = await _upstream(record, reply=b"HTTP/1.1 403 Forbidden\r\n\r\n")
    _system_proxy(monkeypatch, port)
    _answers(monkeypatch, {"duckduckgo.com": "198.18.0.35"})
    async with bp.PublicTunnel() as proxy:
        assert b"403" in await _request(proxy.port, "duckduckgo.com:443")
    server.close()
    await server.wait_closed()
    assert proxy.blocked == 1


@pytest.mark.parametrize("scheme", ["socks5", "https"])
def test_only_http_proxies_are_chained(monkeypatch, scheme):
    _system_proxy(monkeypatch, 7899, scheme=scheme)
    assert bp._upstream_proxy("duckduckgo.com") is None


def test_a_bypassed_host_is_not_chained(monkeypatch):
    _system_proxy(monkeypatch, 7899)
    monkeypatch.setattr(net_pin, "proxy_bypass", lambda host: True)
    assert bp._upstream_proxy("duckduckgo.com") is None


@pytest.mark.asyncio
async def test_a_fake_answer_passes_only_because_a_proxy_resolves_the_name(monkeypatch):
    """Pin the canary to "ordinary DNS", so the result does not depend on this machine's own
    resolver (a fake-IP Mac would answer "fake" and let the name through either way): a fake
    answer is refused when we would dial it ourselves, and passes when the proxy resolves."""
    monkeypatch.setattr(net_pin, "_fake_ip_dns", lambda: False)
    _answers(monkeypatch, {"duckduckgo.com": "198.18.0.35"})
    record: list[bytes] = []
    server, port = await _upstream(record)
    async with bp.PublicTunnel() as proxy:
        assert b"403" in await _request(proxy.port, "duckduckgo.com:443")     # no proxy
        assert record == []
        _system_proxy(monkeypatch, port)
        assert b"200" in await _request(proxy.port, "duckduckgo.com:443")     # proxy resolves
    server.close()
    await server.wait_closed()
    assert record == [b"CONNECT duckduckgo.com:443 HTTP/1.1\r\nHost: duckduckgo.com:443\r\n\r\n"]
    assert proxy.blocked == 1


@pytest.mark.parametrize("proxies, expected", [
    ({"https": "http://127.0.0.1:7899"}, ("127.0.0.1", 7899)),
    ({"https": "127.0.0.1:7899"}, ("127.0.0.1", 7899)),         # no scheme: read as http://
    ({"all": "http://127.0.0.1:7899"}, ("127.0.0.1", 7899)),    # ALL_PROXY
    ({"https": "http://proxy.lan"}, ("proxy.lan", 80)),          # no port: http's default
    ({"http": "http://127.0.0.1:7899"}, None),                   # that one is for http, not https
    ({}, None),
])
def test_upstream_proxy_reads_the_setting(monkeypatch, proxies, expected):
    monkeypatch.setattr(net_pin, "getproxies", lambda: proxies)
    monkeypatch.setattr(net_pin, "proxy_bypass", lambda host: False)
    assert bp._upstream_proxy("duckduckgo.com") == expected
