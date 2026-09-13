import asyncio

import pytest

from server.services import browser_proxy as bp


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
