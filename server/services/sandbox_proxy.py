"""The local proxy a sandboxed command reaches the network through (SBX-6, v0.1.64; the user's N-a).

Online, a command's kernel profile allows TCP only to this proxy's loopback port, plus other loopback ports
for local dev servers, minus every port Arslan itself listens on and the system proxies' loopback ports
(`excluded_ports`). There is no DNS inside: the proxy resolves. Nothing else gets out, and each host it connects to is
named in Arslan's log.

NET-a (v0.1.64): each command's proxy address carries its own token (`proxy_url`, `net_policy.start_run`), and the
proxy serves only a connection whose token belongs to a running command: none, or one whose command ended, is a 407.
It judges the host first (`net_policy.admits`: a site this conversation saw only in outside content is a 403), then
runs its own checks below as before.

It speaks CONNECT, to any port, and plain-http forwarding (absolute-form requests). Every destination is
resolved once and every answer must be public (`net_pin`, as the browser's tunnel does), so a command can't
reach Arslan's own ports, a LAN host or a link-local service through it; a LAN host needs a trusted device or a
run outside the sandbox. A refusal names itself (`DENIED`), so the command's output tells the model why.
With a system HTTP proxy set it chains through it. A tunnel to :443 goes by name, as `browser_proxy` does:
Arslan's check still runs first, but the system proxy then resolves the name and picks the real destination,
so the public-address check is delegated to it there. Everything else, plain http included, goes to the one
address Arslan checked, so a second lookup upstream can't turn it into a LAN host or one of this Mac's ports.

Known limits (SBX-6a review):
- The denied loopback ports are a snapshot when a command starts. A listener Arslan opens later (a browser
  tunnel, an OAuth callback) is reachable from a command already running; both are bounded (the tunnel takes
  public destinations only, the callback needs its state and PKCE).
- A local proxy this Mac doesn't announce (in the environment or `scutil`), such as Tor's SOCKS port or
  `ssh -D`, is reachable through loopback like any dev server.
- A token is a running command's, not a secret from this Mac: anything that reads that command's environment while it
  runs can use the proxy as that command, which is no more than that thing could do itself.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import suppress
import ipaddress
import json
import logging
import os
import re
import socket
import subprocess
from urllib.parse import urlsplit
import weakref

from arslan.aio import close_connection, within
from server.registry.net_pin import _BlockedHost, _FakeIpOnlyHttps, _InvalidHost, _resolve_pinned, _Unresolvable
from server.services import browser_proxy, net_policy

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


# ── trusted local devices (the user's decision, 2026-11-02) ─────────────────
# The LAN stays refused through the proxy, except the specific devices the user listed (a NAS, a Mac mini): never a
# range. A listed name is pinned to the address recorded when it was added (or to a listed IP), and re-checked on
# every connect, so a name rebound to another private address is refused. Loopback and link-local are never
# trusted (Arslan's own ports, metadata services). sandbox-runtime's proxy-only mode refuses private ranges reached
# by name too (src/sandbox/proxy-only.ts:47-51).

def _is_public_literal(name: str) -> bool:
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        return False
    return ip.is_global


def _ip(address: str):
    """An address, with an IPv4-mapped IPv6 one read as its IPv4 address (not left to the interpreter's rules)."""
    ip = ipaddress.ip_address(address.split("%")[0])
    return ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped else ip


_OWN_TTL = 60.0
_own: tuple[float, frozenset[str]] = (-_OWN_TTL, frozenset())


def own_addresses() -> frozenset[str]:
    """This Mac's own interface addresses (ifconfig), cached for a minute. Trusting one would expose every service
    this Mac listens on all interfaces to sandboxed commands (#668 review)."""
    global _own
    import time
    now = time.monotonic()
    if now - _own[0] < _OWN_TTL:
        return _own[1]
    try:
        out = subprocess.run(["/sbin/ifconfig"], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    found = set()
    for word in re.findall(r"^\s+inet6? (\S+)", out, re.M):
        try:
            found.add(str(_ip(word)))
        except ValueError:
            continue
    _own = (now, frozenset(found))
    return _own[1]


def _private(address: str) -> bool:
    ip = _ip(address)
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return False
    return ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10")


def parse_trusted(raw: str | None) -> list[dict]:
    """The setting's JSON list of {"host"?: name, "address": IP}. Anything malformed trusts nothing, and neither do
    this Mac's own addresses. Trusting a device trusts every port on it."""
    try:
        entries = json.loads(raw) if raw else []
    except ValueError:
        return []
    out = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        address, host = entry.get("address"), entry.get("host")
        try:
            if not isinstance(address, str) or not _private(address) or str(_ip(address)) in own_addresses():
                continue
        except ValueError:
            continue
        out.append({"address": str(_ip(address)),
                    **({"host": host.strip().lower()} if isinstance(host, str) and host.strip() else {})})
    return out


def trusted_address(host: str, trusted: list[dict], resolve=None) -> str | None:
    """The one address to connect to when `host` is a listed device, else None (the destination stays refused).
    A literal must be listed. A name must be listed and every answer must be its recorded address or a listed IP.
    SBX settings: an answer no entry could ever hold (public, loopback, link-local) isn't counted, since an mDNS name
    such as nas.local answers its IPv6 link-local address too; any other answer still refuses the name, and the
    connection still goes only to a pinned or listed address."""
    name = host.strip("[]").lower()
    resolve = resolve or socket.getaddrinfo
    listed = {e["address"] for e in trusted}
    try:
        literal = str(_ip(name))
    except ValueError:
        literal = None
    if literal is not None:
        return literal if literal in listed else None
    pinned = {e["address"] for e in trusted if e.get("host") == name}
    if not pinned:
        return None
    try:
        answers = {str(_ip(info[4][0])) for info in resolve(name, None)}
        answers = {a for a in answers if _private(a)}
    except (OSError, ValueError):
        return None
    if not answers or not answers <= (pinned | listed):
        return None
    return sorted(answers & pinned or answers)[0]


def _dial(address: str, port: int):
    """A trusted device's connection (a seam: tests stand the device in on loopback)."""
    return asyncio.open_connection(address, port)


async def _trusted() -> list[dict]:
    try:
        from server.db import session as db_session
        from server.services import settings_service
        async with db_session.AsyncSessionLocal() as db:
            return parse_trusted(await settings_service.sandbox_trusted_devices(db))
    except Exception:  # noqa: BLE001 — a setting that can't be read trusts nothing
        return []


# ── what the proxy refused while a command ran (SBX settings: the LAN card) ──
# The tool loop watches the proxy while one run_command call runs, and trusted_devices.offer turns a LAN device it
# refused meanwhile into a card. The proxy can't tell which command a connection came from (it takes no credentials),
# so a refusal reaches every watch open at that moment: a command running beside another may see the other's, which is
# why a card is offered only when a single device was refused. A watch only collects names; it trusts nothing.

class _Watch:
    __slots__ = ("hosts", "__weakref__")

    def __init__(self):
        self.hosts: list[str] = []


_watches: weakref.WeakSet[_Watch] = weakref.WeakSet()
_WATCHED = 8         # hosts kept per watch


def watch() -> _Watch:
    w = _Watch()
    _watches.add(w)
    return w


def unwatch(w: _Watch | None) -> list[str]:
    """The hosts the proxy refused while `w` was open, and `w` closed. A watch its command dropped (a stop) goes with
    it: the set holds it weakly."""
    if w is None:
        return []
    _watches.discard(w)
    return list(w.hosts)


def _note_refused(host: str) -> None:
    name = host.strip("[]").lower()
    for w in list(_watches):
        if name not in w.hosts and len(w.hosts) < _WATCHED:
            w.hosts.append(name)


# ── the proxy ────────────────────────────────────────────────────────────────

# What the proxy answers when it won't carry a request: a fixed status and reason, sent again as a short text body
# for a client that shows the body (curl without -f). Never a host, an address, a URL or a setting's value.
# Only a destination the sandbox keeps closed is a 403, so a 403 from this proxy is always the sandbox's: curl and git
# print only the code (#668 ruling). `command_sandbox._PROXY_REFUSED` reads DENIED's reason.
DENIED = (403, "Forbidden by Arslan's sandbox: local or non-public destination")
#: NET-a: a site this conversation saw only in outside content (`net_policy.admits`). A 403 too, so curl's and git's
#: code-only refusal still reads as the sandbox's; the run's note names the site.
OUTSIDE_ONLY = (403, "Forbidden by Arslan's sandbox: a site seen only in outside content this conversation read")
#: NET-a: no running command's token (none, a foreign one, or one whose command ended). With its challenge, so a client
#: that sends credentials only when asked (git's default, curl --proxy-anyauth) sends them.
NO_TOKEN = (407, "Proxy Authentication Required by Arslan's sandbox proxy")
BAD_REQUEST = (400, "Bad Request: Arslan's sandbox proxy takes CONNECT and absolute plain-http requests")
UNREACHABLE = (502, "Bad Gateway: Arslan's sandbox proxy could not resolve or reach the destination")
BUSY = (503, "Service Unavailable: Arslan's sandbox proxy has too many open connections")
_BASIC = re.compile(r"(?im)^proxy-authorization:[ \t]*basic[ \t]+([A-Za-z0-9+/=]+)[ \t]*\r?$")


def proxy_url(port: int, token: str | None) -> str:
    """The proxy address a run is told (NET-a): its token as the user, with a password, since git asks a credential
    helper for a proxy password it isn't given, and urllib and Node's fetch send no credentials without one. With no
    token, the bare address, which the proxy answers with its 407."""
    return f"http://{token}:sandbox@127.0.0.1:{port}" if token else f"http://127.0.0.1:{port}"


def _token(headers: str) -> str | None:
    """The token of a run's proxy address (`proxy_url`): the user part of the request's Basic credentials."""
    found = _BASIC.search(headers)
    if found is None:
        return None
    try:
        return base64.b64decode(found[1], validate=True).decode("latin-1").partition(":")[0] or None
    except ValueError:                                   # binascii.Error is one
        return None


class _Refused(Exception):
    def __init__(self, why: str, answer: tuple[int, str] = BAD_REQUEST):
        super().__init__(why)
        self.answer = answer


def _answer(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, _Refused):
        return exc.answer
    if isinstance(exc, (_Unresolvable, OSError)):           # TimeoutError is an OSError
        return UNREACHABLE
    if isinstance(exc, _InvalidHost):
        return BAD_REQUEST
    if isinstance(exc, _BlockedHost):                       # a local name, a non-public answer, fake-IP off :443
        return DENIED
    return BAD_REQUEST                                      # an unreadable request: a bad value, a short or long head


def _refusal(answer: tuple[int, str]) -> bytes:
    status, reason = answer
    body = f"{reason}\n".encode("ascii")
    challenge = 'Proxy-Authenticate: Basic realm="Arslan sandbox"\r\n' if status == 407 else ""
    return (f"HTTP/1.1 {status} {reason}\r\n{challenge}Content-Type: text/plain\r\nContent-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n").encode("ascii") + body


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
        """A stream to host:port, direct to its one checked public address, or through the system proxy, by name
        only for a tunnel to :443 and at the checked address otherwise.
        `first` is sent before the relay starts: a forwarded request's head, which also marks it plain http.
        A tunnel is checked as https (net_pin lets a fake-IP name through only for https on port 443)."""
        name = host.strip("[]").lower()
        url = f"{'http' if first else 'https'}://{host}:{port}/"
        device = None if _is_public_literal(name) else await within(
            asyncio.to_thread(trusted_address, name, await _trusted()), 5)    # DNS off the loop
        try:
            chain = None if device is not None else browser_proxy._upstream_proxy(name)
        except ValueError:                                   # a system proxy setting it can't use: nothing goes
            raise _Refused("the system proxy setting is unusable", UNREACHABLE) from None
        if device is not None:
            # A device the user trusts, at its pinned address, directly (a system proxy can't reach the LAN).
            remote, upstream = await within(_dial(device, port), 8, dispose=close_connection)
        elif chain is not None:
            if first is None and port == 443:
                await within(asyncio.to_thread(_resolve_pinned, url, via_proxy=True), 5)
                target = f"{host}:{port}"
                browser_proxy._warn_once(("sandbox delegated", chain.host, chain.port),
                                         "sandbox proxy: tunnels to port 443 go through the system proxy %s:%s by "
                                         "name; it resolves each name, so the address check is delegated there",
                                         chain.host, chain.port)
            else:
                ip, _, pinned = await within(asyncio.to_thread(_resolve_pinned, url), 5)
                target = f"[{ip}]:{pinned}" if ":" in ip else f"{ip}:{pinned}"
            remote, upstream = await within(asyncio.open_connection(chain.host, chain.port), 8,
                                            dispose=close_connection)
            lines = [f"CONNECT {target} HTTP/1.1", f"Host: {target}"]
            if chain.auth:
                lines.append(f"Proxy-Authorization: {chain.auth}")
            upstream.write(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
            await upstream.drain()
            try:
                head = await within(remote.readuntil(b"\r\n\r\n"), 8)
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
                head = b""                                   # it closed, or sent no HTTP head
            if not re.match(rb"HTTP/1\.[01] 200\b", head):
                upstream.close()
                raise _Refused("the upstream proxy refused", UNREACHABLE)
        else:
            ip, _, pinned = await within(asyncio.to_thread(_resolve_pinned, url), 5)
            remote, upstream = await within(asyncio.open_connection(ip, pinned), 8, dispose=close_connection)
        logger.info("sandbox proxy: %s:%s", name, port)
        if first:
            upstream.write(first)
            await upstream.drain()
        return remote, upstream

    @staticmethod
    async def _judged(run, host: str) -> None:
        """NET-a: the run's judgement of `host`, before this proxy's own checks (`_open`), which still run after it."""
        if not await net_policy.admits(run, host):
            raise _Refused("a site seen only in outside content", OUTSIDE_ONLY)

    async def _copy(self, reader, writer, last: list[float]):
        """One direction. `last` is the connection's one idle clock, shared by both directions: a tunnel
        is idle only when neither side has sent anything for `_IDLE_S` (6a delta review)."""
        loop = asyncio.get_running_loop()
        while True:
            left = _IDLE_S - (loop.time() - last[0])
            if left <= 0:
                raise TimeoutError("idle")
            try:
                block = await within(reader.read(65536), left)
            except TimeoutError:
                continue                                     # the loop's check decides
            if not block:
                break
            last[0] = loop.time()
            writer.write(block)
            # A peer that stops reading would hold drain() forever, and with it a slot (6a delta review):
            # it gets the same idle time to take the block.
            await within(writer.drain(), _IDLE_S)
        with suppress(OSError):
            writer.write_eof()

    async def _accept(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        upstream = None
        relays = []
        established = False
        host = None
        try:
            if len(self.tasks) > _CONNECTIONS:
                raise _Refused("too many connections", BUSY)
            async with asyncio.timeout(30):
                raw = await reader.readuntil(b"\r\n\r\n")
                line, _, headers = raw.decode("latin-1").partition("\r\n")
                parts = line.split(" ")
                if len(parts) != 3 or not re.fullmatch(r"HTTP/1\.[01]", parts[2]):
                    raise _Refused("bad request line")
                method, target, _version = parts
                run = net_policy.run_for(_token(headers))          # NET-a: whose connection this is
                if run is None:
                    raise _Refused("no running command's token", NO_TOKEN)
                if method == "CONNECT":
                    host, port = _authority(target, None)
                    await self._judged(run, host)
                    remote, upstream = await self._open(host, port, None)
                    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    await writer.drain()
                else:
                    url = urlsplit(target)
                    if url.scheme != "http" or not url.netloc or "@" in url.netloc:
                        raise _Refused("only absolute http:// requests are forwarded")
                    host, port = _authority(url.netloc, 80)
                    await self._judged(run, host)
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
                asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
            if not established:
                answer = _answer(exc)
                if answer is DENIED and host and not isinstance(exc, _FakeIpOnlyHttps):    # a public name behind a
                    _note_refused(host)                                                    # fake-IP TUN is no device
                with suppress(OSError):
                    writer.write(_refusal(answer))
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
