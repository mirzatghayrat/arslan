"""Per-visit HTTPS CONNECT tunnel: public destinations only, no TLS interception.

Connecting directly, the tunnel connects to the address it validated: the name is resolved
once, every answer must pass `net_pin`, and the connection goes to that address. That address
is public, except on a Mac whose DNS is fake-IP (a TUN-mode proxy, 0.1.61): there it is the
name's stand-in in 198.18.0.0/15, which the TUN maps back to the name and routes, so the TUN
decides the real destination. The tunnel only ever asks for https on port 443, the one request
`net_pin` lets a faked name make, and TLS, checked by Chromium against the real name, bounds
who can answer. With a system HTTP proxy set (0.1.61) the destination check still runs first,
and the proxy then connects BY NAME, so the pinning is the proxy's and not ours (see the last
paragraph).

Chromium's trusted network service is configured to route page requests here;
scripts, QUIC and proxy bypasses are disabled by the preview service. This is
NOT kernel-enforced egress isolation for the Node/Chromium parent processes.
TLS remains end-to-end and certificate validation stays enabled in Chromium.
This is a destination boundary, not HTTP-method filtering or a filesystem jail.

With a system HTTP proxy set (0.1.61), the tunnel chains through it BY NAME: the proxy
resolves and connects, which is where fake-IP DNS lives, and dialling a fake address
ourselves only works under a TUN. The destination check still runs first, so a local
name or a real private answer is refused before the proxy is asked. The proxy then resolves
the name itself, so "resolve once, connect to that address" is delegated to it, and a
warning says so (once per proxy per 10 minutes; each name at DEBUG, so a page that mints
fresh names cannot flood the log). Credentials in the proxy URL go out as
`Proxy-Authorization: Basic` on the CONNECT and are never logged.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import suppress
import logging
import re
import time
from typing import NamedTuple
from urllib.parse import unquote, urlsplit

from server.registry import net_pin
from server.registry.net_pin import _BlockedHost, _resolve_pinned
from arslan.aio import close_connection, within

logger = logging.getLogger(__name__)

#: Each warning is said at most once per key per this many seconds: one page makes dozens of
#: tunnels, and each would say the same thing. A key names a proxy, never a destination ...
_WARN_EVERY = 600.0
#: ... and the table remembers at most this many keys, so a long-lived server cannot grow
#: without bound.
_WARN_KEYS = 256
#: key -> time.monotonic() of its last warning. Module state, so tests that look at the log
#: reset it.
_warned: dict[tuple, float] = {}


def _warn_once(key: tuple, message: str, *args) -> None:
    """Log a warning at most once per `key` per 10 minutes: a bounded table, purged of stale
    keys when it fills, then cleared. Keys name the proxy and what happened, never the
    destination, so a page that mints fresh names cannot multiply them (net_pin keys its own
    delegation warnings by path for the same reason)."""
    now = time.monotonic()
    last = _warned.get(key)
    if last is not None and now - last < _WARN_EVERY:
        return
    if len(_warned) >= _WARN_KEYS:
        for stale, then in list(_warned.items()):
            if now - then >= _WARN_EVERY:
                _warned.pop(stale, None)
        if len(_warned) >= _WARN_KEYS:
            _warned.clear()
    _warned[key] = now
    logger.warning(message, *args)


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


class _UpstreamProxy(NamedTuple):
    """Where to chain: the proxy's address, and the `Proxy-Authorization` value when its URL
    carried credentials. NOTE: `auth` IS the credentials (base64 hides nothing), so it is never
    logged, and `repr` leaves it out so that an accidental `%s` cannot print it."""
    host: str
    port: int
    auth: str | None = None

    def __repr__(self) -> str:
        return (f"_UpstreamProxy(host={self.host!r}, port={self.port!r}, "
                f"auth={'<hidden>' if self.auth else None})")


def _upstream_proxy(host: str) -> _UpstreamProxy | None:
    """The system or environment HTTPS proxy to chain through. Only plain http:// proxies
    speak CONNECT the way this tunnel does; anything else (socks, https) keeps the direct
    path. A user name in the proxy URL becomes `Proxy-Authorization: Basic`, read the way
    urllib reads it (percent-decoded, UTF-8).

    A value that cannot be parsed, has no scheme, has no host, names port 0, or has an '@'
    outside its netloc raises ValueError, which `_accept` answers with a refusal: a broken
    proxy setting is not a licence to go direct. Only a scheme that is there and is not http
    returns None (that proxy is not ours to speak to). `host` is the destination as the page
    wrote it, lower case and without brackets, for NO_PROXY and the system exception list; a
    trailing dot is kept (stripping it would change what those lists match).

    The error carries a fixed text, never the value or the parser's message, and is raised
    after the handler so that it is not chained to the parser's error either: both can quote
    the password (urlsplit's does for a netloc that normalises to something else), and a chain
    is printed by whatever reports it."""
    proxies = net_pin.getproxies()
    if not proxies:
        return None
    raw = proxies.get("https") or proxies.get("all")
    if not raw or net_pin.proxy_bypass(host):
        return None
    try:
        parsed = urlsplit(raw if "://" in raw else f"http://{raw}")
        if not parsed.scheme:
            # Nothing readable before the "://" (HTTPS_PROXY=$SCHEME://host:7899, SCHEME unset):
            # refused below like an unparsable value, not taken for somebody else's proxy.
            raise ValueError
        if parsed.scheme != "http":
            return None
        if "@" in raw and "@" not in parsed.netloc:
            # An '@' outside the netloc: `http://user:12345/word@proxy:8080` reads as host
            # "user", port 12345, a user name and the start of a password, which the log lines
            # would then print. Whatever was meant, this is not it: refused below.
            raise ValueError
        port = parsed.port
        if not parsed.hostname or port == 0:
            # HTTPS_PROXY=http://$UNSET_VARIABLE:7899 has no host, and port 0 is nobody's port:
            # both are broken settings, refused below like an unparsable one.
            raise ValueError
        auth = None
        if parsed.username or parsed.password:
            credentials = f"{unquote(parsed.username or '')}:{unquote(parsed.password or '')}"
            auth = "Basic " + base64.b64encode(credentials.encode()).decode("ascii")
    except ValueError:      # also UnicodeEncodeError: a byte the environment could not decode
        pass                # refused below, outside the handler (see the docstring)
    else:
        return _UpstreamProxy(parsed.hostname, 80 if port is None else port, auth)
    _warn_once(("malformed",), "browser tunnel: the system proxy setting is malformed; "
                               "every tunnel is refused until it is fixed")
    raise ValueError("The system proxy setting is malformed")


def _connect_request(host: str, proxy: _UpstreamProxy) -> bytes:
    lines = [f"CONNECT {host}:443 HTTP/1.1", f"Host: {host}:443"]
    if proxy.auth:
        lines.append(f"Proxy-Authorization: {proxy.auth}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")


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
                name = host.strip("[]").lower()
                chain = _upstream_proxy(name)
                if chain is not None:
                    # The proxy resolves and connects; we still refuse a local name or a real
                    # private answer first (fake-IP answers pass: via_proxy).
                    await within(
                        asyncio.to_thread(_resolve_pinned, url, via_proxy=True), 5)
                    # Keyed by the proxy, never the destination: a page can mint a fresh name
                    # for every tunnel, and each would be a WARNING. The name goes to DEBUG.
                    logger.debug("browser tunnel: %s via the system proxy %s:%s",
                                 name, chain.host, chain.port)
                    _warn_once(("delegated", chain.host, chain.port),
                               "browser tunnel: tunnels go through the system proxy %s:%s, which "
                               "resolves each name; rebinding protection is delegated there "
                               "(each name is logged at DEBUG)", chain.host, chain.port)
                    try:
                        remote, upstream = await within(
                            asyncio.open_connection(chain.host, chain.port), 8, dispose=close_connection)
                        upstream.write(_connect_request(host, chain))
                        await upstream.drain()
                        head = await within(remote.readuntil(b"\r\n\r\n"), 8)
                    except (OSError, TimeoutError, asyncio.IncompleteReadError,
                            asyncio.LimitOverrunError) as exc:
                        _warn_once(("unreachable", chain.host, chain.port),
                                   "browser tunnel: upstream proxy %s:%s unreachable (%s)",
                                   chain.host, chain.port, type(exc).__name__)
                        raise
                    if not re.match(rb"HTTP/1\.[01] 200\b", head):
                        status = re.match(rb"HTTP/1\.[01] (\d{3})\b", head)
                        what = f"HTTP {status[1].decode('ascii')}" if status else "a non-HTTP reply"
                        logger.debug("browser tunnel: upstream proxy %s:%s refused the tunnel "
                                     "to %s (%s)", chain.host, chain.port, name, what)
                        _warn_once(("refused", chain.host, chain.port, what),
                                   "browser tunnel: upstream proxy %s:%s refused a tunnel (%s); "
                                   "each refused name is logged at DEBUG",
                                   chain.host, chain.port, what)
                        raise ValueError("The upstream proxy refused the tunnel")
                else:
                    # Resolver rejects EVERY non-public answer. Connect by IP, never resolve twice.
                    ip, _, port = await within(asyncio.to_thread(_resolve_pinned, url), 5)
                    remote, upstream = await within(asyncio.open_connection(ip, port), 8,
                                                    dispose=close_connection)
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
                        await within(stream.wait_closed(), 1)
            self.tasks.discard(task)
