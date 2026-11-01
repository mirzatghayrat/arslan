"""The local proxy a sandboxed command reaches the network through (SBX-6, v0.1.64; the user's N-a).

Online, a command's kernel profile allows TCP only to this proxy's loopback port, plus other loopback ports
for local dev servers, minus every port Arslan itself listens on and the system proxies' loopback ports
(`excluded_ports`). There is no DNS inside: the proxy resolves. It has no site list (NET adds one in
v0.1.65). What it adds now is that nothing else gets out, and that each host it connects to is named in
Arslan's log.

It speaks CONNECT, to any port, and plain-http forwarding (absolute-form requests). Every destination is
resolved once and every answer must be public (`net_pin`, as the browser's tunnel does), so a command can't
reach Arslan's own ports, a LAN host or a link-local service through it; a LAN host needs the re-run card.
With a system HTTP proxy set it chains through it by name, with a CONNECT for plain http too, as
`browser_proxy` does: Arslan's check still runs first, but the system proxy then resolves the name and
picks the real destination, so the public-address check is delegated to it.

Known limits (SBX-6a review):
- The denied loopback ports are a snapshot when a command starts. A listener Arslan opens later (a browser
  tunnel, an OAuth callback) is reachable from a command already running; both are bounded (the tunnel takes
  public destinations only, the callback needs its state and PKCE).
- A local proxy this Mac doesn't announce (in the environment or `scutil`), such as Tor's SOCKS port or
  `ssh -D`, is reachable through loopback like any dev server.
- The proxy takes no client credentials, like `browser_proxy`: anything on this Mac that can reach its port
  can use it, which is no more than that thing could do itself.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import ipaddress
import logging
import os
import re
import subprocess
from urllib.parse import urlsplit

from arslan.aio import close_connection, within
from server.registry.net_pin import _BlockedHost, _resolve_pinned
from server.services import browser_proxy

logger = logging.getLogger(__name__)

_HEADER_LIMIT = 65536
_PICKS = 4           # free ports tried when one collides with a system proxy's number
_CONNECTIONS = 64    # open connections at once; more are refused
_IDLE_S = 300        # a relay with nothing to read for this long is closed
_DEFAULT_PORTS = {"http": 80, "https": 443, "socks": 1080, "socks4": 1080, "socks4a": 1080, "socks5": 1080,
                  "socks5h": 1080}
_PROXY_ENV = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_SCUTIL_LINE = re.compile(r"^\s*(\w+) : (.+?)\s*$", re.MULTILINE)


# ── the ports proxy mode refuses on loopback ─────────────────────────────────

def listening_ports() -> list[int] | None:
    """The TCP ports this process listens on, now: the API, the browser's tunnels, the proxy itself and any
    other. None when they can't be read, so the caller fails closed."""
    try:
        out = subprocess.run(["/usr/sbin/lsof", "-a", "-n", "-P", "-p", str(os.getpid()), "-iTCP",
                              "-sTCP:LISTEN", "-Fn"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    ports = set()
    for line in out.stdout.splitlines():
        if line.startswith("n"):
            port = line.rsplit(":", 1)[-1]
            if not port.isdigit():
                return None
            ports.add(int(port))
    return sorted(ports)


def _scutil() -> str:
    try:
        return subprocess.run(["/usr/sbin/scutil", "--proxy"], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def system_proxies() -> list[str]:
    """The proxies this Mac is set to use: the environment's, then the system's (HTTP, HTTPS, SOCKS)."""
    urls = [os.environ[name] for name in _PROXY_ENV if os.environ.get(name)]
    fields = dict(_SCUTIL_LINE.findall(_scutil()))
    for kind, scheme in (("HTTP", "http"), ("HTTPS", "http"), ("SOCKS", "socks5")):
        host, port = fields.get(f"{kind}Proxy"), fields.get(f"{kind}Port")
        if fields.get(f"{kind}Enable") == "1" and host and port:
            urls.append(f"{scheme}://{host}:{port}")
    return list(dict.fromkeys(urls))


def _loopback_port(setting: str) -> int | None:
    try:
        parts = urlsplit(setting if "://" in setting else "http://" + setting)
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if not host:
        return None
    if host != "localhost":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                return None
        except ValueError:
            return None
    return port or _DEFAULT_PORTS.get(parts.scheme.lower())


def system_loopback_ports(system) -> set[int]:
    return {p for p in map(_loopback_port, system) if p}


def excluded_ports(bound, system, *, proxy_port: int) -> tuple[int, ...]:
    """What proxy mode denies on loopback: Arslan's own listening ports and the system proxies' loopback
    ports (a command would otherwise reach the Internet through either), never the proxy's own.

    A system proxy on the proxy's own port number is refused (ValueError): a port rule can't tell an IPv4
    listener from an IPv6 one on the same number (SBX-6p review), so allowing ours would allow theirs."""
    theirs = system_loopback_ports(system)
    if proxy_port in theirs:
        raise ValueError(f"the sandbox proxy port {proxy_port} is also a system proxy's port")
    return tuple(sorted(p for p in {*bound, *theirs} if p != proxy_port and 1 <= p <= 65535))


# ── the proxy ────────────────────────────────────────────────────────────────

class _Refused(Exception):
    pass


def _authority(text: str, default: int | None) -> tuple[str, int]:
    match = re.fullmatch(r"(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.\-]+)(?::(\d{1,5}))?", text)
    if not match or (match[2] is None and default is None):
        raise _Refused("bad authority")
    port = int(match[2]) if match[2] is not None else default
    if not 1 <= port <= 65535:
        raise _Refused("bad port")
    return match[1], port


class LocalProxy:
    def __init__(self):
        self.server = None
        self.port: int | None = None
        self.tasks: set[asyncio.Task] = set()

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._accept, "127.0.0.1", 0, limit=_HEADER_LIMIT)
        self.port = self.server.sockets[0].getsockname()[1]
        return self.port

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            with suppress(Exception):
                await self.server.wait_closed()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def _open(self, host: str, port: int, first: bytes | None):
        """A stream to host:port, direct to its one checked public address, or through the system proxy.
        `first` is sent before the relay starts: a forwarded request's head, which also marks it plain http.
        A tunnel is checked as https (net_pin lets a fake-IP name through only for https on port 443)."""
        name = host.strip("[]").lower()
        url = f"{'http' if first else 'https'}://{host}:{port}/"
        chain = browser_proxy._upstream_proxy(name)          # ValueError: a broken setting is refused
        if chain is not None:
            await within(asyncio.to_thread(_resolve_pinned, url, via_proxy=True), 5)
            remote, upstream = await within(asyncio.open_connection(chain.host, chain.port), 8,
                                            dispose=close_connection)
            lines = [f"CONNECT {host}:{port} HTTP/1.1", f"Host: {host}:{port}"]
            if chain.auth:
                lines.append(f"Proxy-Authorization: {chain.auth}")
            upstream.write(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
            await upstream.drain()
            head = await within(remote.readuntil(b"\r\n\r\n"), 8)
            if not re.match(rb"HTTP/1\.[01] 200\b", head):
                upstream.close()
                raise _Refused("the upstream proxy refused")
        else:
            ip, _, pinned = await within(asyncio.to_thread(_resolve_pinned, url), 5)
            remote, upstream = await within(asyncio.open_connection(ip, pinned), 8, dispose=close_connection)
        logger.info("sandbox proxy: %s:%s", name, port)
        if first:
            upstream.write(first)
            await upstream.drain()
        return remote, upstream

    async def _copy(self, reader, writer, last: list[float]):
        """One direction. `last` is the connection's one idle clock, shared by both directions: a tunnel
        is idle only when neither side has sent anything for `_IDLE_S` (6a delta review)."""
        loop = asyncio.get_running_loop()
        while True:
            left = _IDLE_S - (loop.time() - last[0])
            if left <= 0:
                raise TimeoutError("idle")
            try:
                block = await asyncio.wait_for(reader.read(65536), left)
            except TimeoutError:
                continue                                     # the loop's check decides
            if not block:
                break
            last[0] = loop.time()
            writer.write(block)
            await writer.drain()
        with suppress(OSError):
            writer.write_eof()

    async def _accept(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        upstream = None
        relays = []
        established = False
        try:
            if len(self.tasks) > _CONNECTIONS:
                raise _Refused("too many connections")
            async with asyncio.timeout(30):
                raw = await reader.readuntil(b"\r\n\r\n")
                line, _, headers = raw.decode("latin-1").partition("\r\n")
                parts = line.split(" ")
                if len(parts) != 3 or not re.fullmatch(r"HTTP/1\.[01]", parts[2]):
                    raise _Refused("bad request line")
                method, target, _version = parts
                if method == "CONNECT":
                    host, port = _authority(target, None)
                    remote, upstream = await self._open(host, port, None)
                    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    await writer.drain()
                else:
                    url = urlsplit(target)
                    if url.scheme != "http" or not url.netloc or "@" in url.netloc:
                        raise _Refused("only absolute http:// requests are forwarded")
                    host, port = _authority(url.netloc, 80)
                    path = (url.path or "/") + (f"?{url.query}" if url.query else "")
                    kept = [h for h in headers.split("\r\n") if h and not re.match(
                        r"(?i)(proxy-[\w-]*|connection|keep-alive)\s*:", h)]
                    head = "\r\n".join([f"{method} {path} HTTP/1.1", *kept, "Connection: close"]) + "\r\n\r\n"
                    remote, upstream = await self._open(host, port, head.encode("latin-1"))
                established = True
            last = [asyncio.get_running_loop().time()]
            relays = [asyncio.create_task(self._copy(reader, upstream, last)),
                      asyncio.create_task(self._copy(remote, writer, last))]
            # The connection ends when the server's side ends, or when either side fails or goes idle; a
            # client that only half-closes keeps getting the reply.
            done, _ = await asyncio.wait(relays, return_when=asyncio.FIRST_COMPLETED)
            if relays[1] not in done and relays[0].exception() is None:
                done, _ = await asyncio.wait([relays[1]])
            for finished in done:
                finished.result()
        except (_Refused, _BlockedHost, ValueError, UnicodeError, OSError, TimeoutError,
                asyncio.IncompleteReadError, asyncio.LimitOverrunError):
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


# ── one proxy per server ─────────────────────────────────────────────────────

_proxy: LocalProxy | None = None
_loop: asyncio.AbstractEventLoop | None = None
_starting: asyncio.Lock | None = None


async def port() -> int | None:
    """The running proxy's port, started on first use. None when it can't listen: the run is then offline."""
    global _proxy, _loop, _starting
    loop = asyncio.get_running_loop()
    if _loop is not loop:
        _proxy, _loop, _starting = None, loop, asyncio.Lock()
    async with _starting:
        taken = await asyncio.to_thread(lambda: system_loopback_ports(system_proxies()))
        if _proxy is not None and _proxy.port in taken:
            await _proxy.close()                 # a system proxy now has its number: move (excluded_ports)
            _proxy = None
        for _ in range(_PICKS):
            if _proxy is not None:
                break
            candidate = LocalProxy()
            try:
                await candidate.start()
            except OSError as exc:
                logger.warning("sandbox proxy: can't listen (%s); sandboxed commands run offline", exc)
                return None
            if candidate.port in taken:
                await candidate.close()
                continue
            _proxy = candidate
        return None if _proxy is None else _proxy.port


async def shutdown() -> None:
    global _proxy
    if _proxy is not None and _loop is asyncio.get_running_loop():
        await _proxy.close()
    _proxy = None


def _reset_for_tests() -> None:
    global _proxy, _loop, _starting
    _proxy = _loop = _starting = None
