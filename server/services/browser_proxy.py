"""Per-visit HTTPS CONNECT tunnel: public pinned IPs only, no TLS interception.

Chromium's trusted network service is configured to route page requests here;
scripts, QUIC and proxy bypasses are disabled by the preview service. This is
NOT kernel-enforced egress isolation for the Node/Chromium parent processes.
TLS remains end-to-end and certificate validation stays enabled in Chromium.
This is a destination boundary, not HTTP-method filtering or a filesystem jail.

With a system HTTP proxy set (0.1.61), the tunnel chains through it BY NAME: the proxy
resolves and connects, which is where fake-IP DNS lives, and dialling a fake address
ourselves only works under a TUN. The destination check still runs first, so a local
name or a real private answer is refused before the proxy is asked.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import re
from urllib.parse import urlsplit

from server.registry import net_pin
from server.registry.net_pin import _BlockedHost, _resolve_pinned


def validate_url(url: str) -> str:
    if len(url) > 4000 or any(ord(c) < 33 for c in url) or "\\" in url:
        raise ValueError("Only public HTTPS URLs are supported")
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname and parsed.port in (None, 443)
                 and parsed.username is None and parsed.password is None)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Only public HTTPS URLs on port 443 are supported")
    return url


def _upstream_proxy(host: str) -> tuple[str, int] | None:
    """The system or environment HTTPS proxy to chain through, as (host, port). Only plain
    http:// proxies speak CONNECT the way this tunnel does; anything else (socks, https)
    keeps the direct path."""
    proxies = net_pin.getproxies()
    if not proxies:
        return None
    raw = proxies.get("https") or proxies.get("all")
    if not raw or net_pin.proxy_bypass(host):
        return None
    parsed = urlsplit(raw if "://" in raw else f"http://{raw}")
    if parsed.scheme != "http" or not parsed.hostname:
        return None
    return parsed.hostname, parsed.port or 80


class PublicTunnel:
    def __init__(self, *, byte_limit: int = 50 * 1024 * 1024, connection_limit: int = 32):
        self.byte_limit = byte_limit
        self.connection_limit = connection_limit
        self.bytes = 0
        self.connections = 0
        self.blocked = 0
        self.tasks: set[asyncio.Task] = set()
        self.server = None

    async def __aenter__(self):
        self.server = await asyncio.start_server(self._accept, "127.0.0.1", 0, limit=8192)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *args):
        self.server.close()
        await self.server.wait_closed()
        pending = list(self.tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def _copy(self, reader, writer):
        while block := await reader.read(16384):
            self.bytes += len(block)
            if self.bytes > self.byte_limit:
                raise ValueError("Page transfer budget exhausted")
            writer.write(block)
            await writer.drain()

    async def _accept(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        upstream = None
        relays = []
        established = False
        try:
            self.connections += 1
            if self.connections > self.connection_limit or self.bytes >= self.byte_limit:
                raise ValueError("Page connection budget exhausted")
            async with asyncio.timeout(40):
                raw = await reader.readuntil(b"\r\n\r\n")
                if len(raw) > 8192:
                    raise ValueError("Oversized proxy header")
                first = raw.split(b"\r\n", 1)[0].decode("ascii")
                match = re.fullmatch(r"CONNECT ([A-Za-z0-9.\-\[\]:]+):443 HTTP/1\.[01]", first)
                if not match:
                    raise ValueError("Only HTTPS tunnels to port 443 are allowed")
                host = match[1]
                url = validate_url(f"https://{host}:443/")
                chain = _upstream_proxy(host.strip("[]"))
                if chain is not None:
                    # The proxy resolves and connects; we still refuse a local name or a real
                    # private answer first (fake-IP answers pass: via_proxy).
                    await asyncio.wait_for(
                        asyncio.to_thread(_resolve_pinned, url, via_proxy=True), 5)
                    remote, upstream = await asyncio.wait_for(asyncio.open_connection(*chain), 8)
                    upstream.write(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n"
                                   .encode("ascii"))
                    await upstream.drain()
                    head = await asyncio.wait_for(remote.readuntil(b"\r\n\r\n"), 8)
                    if not re.match(rb"HTTP/1\.[01] 200\b", head):
                        raise ValueError("The upstream proxy refused the tunnel")
                else:
                    # Resolver rejects EVERY non-public answer. Connect by IP, never resolve twice.
                    ip, _, port = await asyncio.wait_for(asyncio.to_thread(_resolve_pinned, url), 5)
                    remote, upstream = await asyncio.wait_for(asyncio.open_connection(ip, port), 8)
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
                established = True
                relays = [asyncio.create_task(self._copy(reader, upstream)),
                          asyncio.create_task(self._copy(remote, writer))]
                done, _ = await asyncio.wait(relays, return_when=asyncio.FIRST_COMPLETED)
                for finished in done:
                    finished.result()
        except (ValueError, UnicodeError, OSError, TimeoutError, _BlockedHost,
                asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            self.blocked += 1
            if not established:
                with suppress(OSError):
                    writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                    await writer.drain()
        finally:
            for relay in relays:
                relay.cancel()
            await asyncio.gather(*relays, return_exceptions=True)
            for stream in (upstream, writer):
                if stream is not None:
                    stream.close()
                    with suppress(OSError, asyncio.CancelledError, TimeoutError):
                        await asyncio.wait_for(stream.wait_closed(), 1)
            self.tasks.discard(task)
