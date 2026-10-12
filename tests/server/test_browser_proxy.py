import asyncio
import base64
import ipaddress
import logging
import socket

import pytest

from server.registry import net_pin
from server.services import browser_proxy as bp


@pytest.fixture(autouse=True)
def no_system_proxy(monkeypatch):
    """The developer Mac has a system proxy (127.0.0.1:7899); without this the tunnel
    would chain through it and the existing tests would dial a real proxy."""
    monkeypatch.setattr(net_pin, "getproxies", lambda: {})


def _addrinfo(ip: str, port: int = 0) -> list[tuple]:
    if ":" in ip:
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, port, 0, 0))]
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


def _literal_or_refuse(table: dict[str, str]):
    """A resolver that answers a literal address with itself, a listed name from `table`, and
    anything else with gaierror. It never asks the real resolver: on this project's fake-IP Mac
    a real answer is a 198.18 address that the TUN routes out to the real internet."""
    def resolve(host, port=None, *args, **kwargs):
        name = host.decode() if isinstance(host, bytes) else str(host)
        if name == "localhost":
            return _addrinfo("127.0.0.1", port or 0)
        try:
            ipaddress.ip_address(name)
        except ValueError:
            if name in table:
                return _addrinfo(table[name], port or 0)
            raise socket.gaierror(socket.EAI_NONAME,
                                  f"test guard: {name!r} is not in this test's table") from None
        return _addrinfo(name, port or 0)
    return resolve


_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


@pytest.fixture(autouse=True)
def hermetic(monkeypatch):
    """Nothing in this file reaches the network, even when the code under test is wrong.

    - The fake-IP canary answers "ordinary DNS" unless a test pins it otherwise: the real one is
      a DNS lookup, and on a fake-IP Mac it answers "fake".
    - No real resolver: a literal answers itself, any name a test did not list fails.
    - A dial to anything but loopback raises `OSError("test guard: non-loopback dial")`, and a
      loopback dial reaches only a server this test started: the developer Mac's real system
      proxy listens on loopback (127.0.0.1:7899) and forwards to the internet. A loopback port
      nobody here listens on is refused the way a dead port is."""
    monkeypatch.setattr(net_pin, "_fake_ip_dns", lambda: False)
    monkeypatch.setattr(socket, "getaddrinfo", _literal_or_refuse({}))
    listening: set[int] = set()
    real_start, real_connect = asyncio.start_server, asyncio.open_connection

    async def start_server(*args, **kwargs):
        server = await real_start(*args, **kwargs)
        listening.update(sock.getsockname()[1] for sock in server.sockets)
        return server

    async def open_connection(host=None, port=None, **kwargs):
        if host not in _LOOPBACK:
            raise OSError("test guard: non-loopback dial")
        if port not in listening:
            raise ConnectionRefusedError(f"test guard: no test server on loopback port {port}")
        return await real_connect(host, port, **kwargs)

    monkeypatch.setattr(asyncio, "start_server", start_server)
    monkeypatch.setattr(bp.asyncio, "open_connection", open_connection)


@pytest.fixture(autouse=True)
def fresh_warnings(monkeypatch):
    """The tunnel's warnings are rate-limited per key in module state: every test starts with
    none said, or one test's warning would silence the next test's."""
    monkeypatch.setattr(bp, "_warned", {})


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


def _answers(monkeypatch, table: dict[str, str]):
    """Answer the names in `table`; a literal answers itself; any other name fails (gaierror).
    Never the real resolver."""
    monkeypatch.setattr(socket, "getaddrinfo", _literal_or_refuse(table))


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


@pytest.mark.asyncio
async def test_a_fake_name_through_the_tunnel_in_tun_mode_is_still_allowed(monkeypatch):
    """The tunnel checks `https://{host}:443/`, the one request a faked name may still make
    (net_pin, R1), so the agent browser keeps working on a fake-IP Mac with no system proxy:
    it dials the stand-in address and the TUN maps it back. Here that dial is redirected to a
    local echo server, so nothing leaves the machine."""
    monkeypatch.setattr(net_pin, "_fake_ip_dns", lambda: True)          # TUN mode
    _answers(monkeypatch, {"duckduckgo.com": "198.18.0.35"})
    async def echo(reader, writer):                                     # stands in for the site
        try:
            writer.write(await reader.read(100))
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(echo, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    dialled: list[tuple] = []
    guarded = asyncio.open_connection

    async def tun(host=None, port_=None, **kwargs):
        dialled.append((host, port_))
        if (host, port_) == ("198.18.0.35", 443):
            return await guarded("127.0.0.1", port, **kwargs)
        return await guarded(host, port_, **kwargs)

    async with bp.PublicTunnel() as proxy:
        monkeypatch.setattr(bp.asyncio, "open_connection", tun)
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
    assert ("198.18.0.35", 443) in dialled
    assert proxy.blocked == 0


def _basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode("ascii")


@pytest.mark.parametrize("proxies, expected", [
    ({"https": "http://127.0.0.1:7899"}, ("127.0.0.1", 7899, None)),
    ({"https": "127.0.0.1:7899"}, ("127.0.0.1", 7899, None)),      # no scheme: read as http://
    ({"all": "http://127.0.0.1:7899"}, ("127.0.0.1", 7899, None)),  # ALL_PROXY
    ({"https": "http://proxy.lan"}, ("proxy.lan", 80, None)),       # no port: http's default
    ({"http": "http://127.0.0.1:7899"}, None),                      # that one is for http only
    ({"https": "socks5://127.0.0.1:notaport"}, None),               # not ours to parse: direct
    ({"https": "socks5://:1080"}, None),                            # ... not even its missing host
    ({}, None),
    # Credentials in the URL become the Proxy-Authorization value, as urllib reads them.
    ({"https": "http://user:pass@127.0.0.1:7899"}, ("127.0.0.1", 7899, _basic("user", "pass"))),
    ({"https": "user:pass@proxy.lan:3128"}, ("proxy.lan", 3128, _basic("user", "pass"))),
    ({"https": "http://alice:s3cret%3Ap%40ss@127.0.0.1:7899"},      # percent-encoded: decoded
     ("127.0.0.1", 7899, _basic("alice", "s3cret:p@ss"))),
    ({"https": "http://token@127.0.0.1:7899"}, ("127.0.0.1", 7899, _basic("token", ""))),
    ({"https": "http://@127.0.0.1:7899"}, ("127.0.0.1", 7899, None)),    # empty: no credentials
])
def test_upstream_proxy_reads_the_setting(monkeypatch, proxies, expected):
    monkeypatch.setattr(net_pin, "getproxies", lambda: proxies)
    monkeypatch.setattr(net_pin, "proxy_bypass", lambda host: False)
    assert bp._upstream_proxy("duckduckgo.com") == expected


# The delegation is logged, a credentialed proxy is spoken to, and a failure names its cause.


def _delegation(port: int) -> str:
    """The WARNING, said once per proxy per 10 minutes: it names the proxy, never a destination,
    so a page that mints fresh names cannot make more of them."""
    return (f"browser tunnel: tunnels go through the system proxy 127.0.0.1:{port}, which "
            "resolves each name; rebinding protection is delegated there (each name is logged "
            "at DEBUG)")


def _delegated_name(name: str, port: int) -> str:
    """The DEBUG detail, said for every tunnel."""
    return f"browser tunnel: {name} via the system proxy 127.0.0.1:{port}"


def _tunnel_log(caplog, level: int | None = None) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.getMessage().startswith("browser tunnel:") and level in (None, r.levelno)]


def _proxy_url(monkeypatch, url: str):
    monkeypatch.setattr(net_pin, "getproxies", lambda: {"https": url})
    monkeypatch.setattr(net_pin, "proxy_bypass", lambda host: False)


def _headers(connect: bytes) -> dict[str, str]:
    """The header fields of a recorded CONNECT, names lower-cased."""
    fields = (line.partition(": ") for line in connect.decode("ascii").split("\r\n")[1:] if line)
    return {name.lower(): value for name, _, value in fields}


def _dead_port() -> int:
    """A loopback port nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _dials(monkeypatch) -> list[tuple]:
    """Record every connection attempted through asyncio, and refuse any that is not loopback:
    a fail-open bug then shows up as a recorded dial and cannot reach the network."""
    calls: list[tuple] = []
    real = asyncio.open_connection

    async def spy(host=None, port=None, **kwargs):
        calls.append((host, port))
        if host != "127.0.0.1":
            raise ConnectionRefusedError("test: no network")
        return await real(host, port, **kwargs)

    monkeypatch.setattr(asyncio, "open_connection", spy)
    return calls


@pytest.mark.asyncio
async def test_chaining_says_the_proxy_decides_once_per_proxy_per_ten_minutes(monkeypatch, caplog):
    server, port = await _upstream([])
    other, other_port = await _upstream([])
    _system_proxy(monkeypatch, port)
    _answers(monkeypatch, {"duckduckgo.com": "198.18.0.35", "news.example": "198.18.0.36"})
    async with bp.PublicTunnel() as proxy:
        with caplog.at_level(logging.DEBUG, logger=bp.logger.name):
            assert b"200" in await _request(proxy.port, "duckduckgo.com:443")
            assert b"200" in await _request(proxy.port, "news.example:443")       # same proxy: silent
            bp._warned[("delegated", "127.0.0.1", port)] -= 601                   # ten minutes pass
            assert b"200" in await _request(proxy.port, "duckduckgo.com:443")
            _system_proxy(monkeypatch, other_port)                                # another proxy: heard
            assert b"200" in await _request(proxy.port, "duckduckgo.com:443")
    for each in (server, other):
        each.close()
        await each.wait_closed()
    assert _tunnel_log(caplog, logging.WARNING) == [_delegation(port), _delegation(port),
                                                    _delegation(other_port)]
    assert _tunnel_log(caplog, logging.DEBUG) == [_delegated_name("duckduckgo.com", port),
                                                  _delegated_name("news.example", port),
                                                  _delegated_name("duckduckgo.com", port),
                                                  _delegated_name("duckduckgo.com", other_port)]


@pytest.mark.asyncio
async def test_fifty_fresh_names_through_one_proxy_make_one_warning(monkeypatch, caplog):
    """A hostile page can mint a fresh name for every request; the agent browser allows a great
    many. The names go to DEBUG, the WARNING stays one."""
    server, port = await _upstream([])
    _system_proxy(monkeypatch, port)
    names = [f"n{i}.evil.test" for i in range(50)]
    _answers(monkeypatch, {name: "198.18.0.35" for name in names})
    async with bp.PublicTunnel(connection_limit=100) as proxy:
        with caplog.at_level(logging.DEBUG, logger=bp.logger.name):
            for name in names:
                assert b"200" in await _request(proxy.port, f"{name}:443")
    server.close()
    await server.wait_closed()
    assert _tunnel_log(caplog, logging.WARNING) == [_delegation(port)]
    assert _tunnel_log(caplog, logging.DEBUG) == [_delegated_name(name, port) for name in names]


@pytest.mark.asyncio
async def test_fifty_names_a_proxy_refuses_make_one_warning(monkeypatch, caplog):
    """The refusal is keyed by the proxy and its answer, not by the name refused."""
    server, port = await _upstream([], reply=b"HTTP/1.1 403 Forbidden\r\n\r\n")
    _system_proxy(monkeypatch, port)
    names = [f"n{i}.evil.test" for i in range(50)]
    _answers(monkeypatch, {name: "198.18.0.35" for name in names})
    async with bp.PublicTunnel(connection_limit=100) as proxy:
        with caplog.at_level(logging.DEBUG, logger=bp.logger.name):
            for name in names:
                assert b"403" in await _request(proxy.port, f"{name}:443")
    server.close()
    await server.wait_closed()
    refused = [line for line in _tunnel_log(caplog, logging.WARNING) if "refused" in line]
    assert refused == [f"browser tunnel: upstream proxy 127.0.0.1:{port} refused a tunnel "
                       "(HTTP 403); each refused name is logged at DEBUG"]
    assert [line for line in _tunnel_log(caplog, logging.DEBUG) if "refused" in line] == [
        f"browser tunnel: upstream proxy 127.0.0.1:{port} refused the tunnel to {name} "
        "(HTTP 403)" for name in names]


def test_the_warning_memory_is_bounded():
    """A long-lived server meets many hosts; the table of who was warned about must not grow
    without limit."""
    for i in range(bp._WARN_KEYS + 50):
        bp._warn_once(("delegated", f"host{i}.example"), "browser tunnel: %s", i)
    assert 0 < len(bp._warned) <= bp._WARN_KEYS


@pytest.mark.asyncio
async def test_a_refused_destination_is_not_reported_as_delegated(monkeypatch, caplog):
    """Nothing is handed to the proxy for a name the check refuses, so nothing is said."""
    server, port = await _upstream([])
    _system_proxy(monkeypatch, port)
    _answers(monkeypatch, {"wiki.example": "10.0.0.5"})
    async with bp.PublicTunnel() as proxy:
        with caplog.at_level(logging.WARNING, logger=bp.logger.name):
            assert b"403" in await _request(proxy.port, "wiki.example:443")
    server.close()
    await server.wait_closed()
    assert _tunnel_log(caplog) == []


@pytest.mark.asyncio
async def test_a_credentialed_proxy_url_sends_basic_auth_on_the_connect(monkeypatch):
    record: list[bytes] = []
    server, port = await _upstream(record)
    _proxy_url(monkeypatch, f"http://user:pass@127.0.0.1:{port}")
    _answers(monkeypatch, {"duckduckgo.com": "198.18.0.35"})
    async with bp.PublicTunnel() as proxy:
        assert b"200" in await _request(proxy.port, "duckduckgo.com:443")
    server.close()
    await server.wait_closed()
    scheme, _, token = _headers(record[0])["proxy-authorization"].partition(" ")
    assert (scheme, base64.b64decode(token)) == ("Basic", b"user:pass")


@pytest.mark.asyncio
async def test_a_proxy_url_without_credentials_sends_no_authorization(monkeypatch):
    record: list[bytes] = []
    server, port = await _upstream(record)
    _system_proxy(monkeypatch, port)
    _answers(monkeypatch, {"duckduckgo.com": "198.18.0.35"})
    async with bp.PublicTunnel() as proxy:
        assert b"200" in await _request(proxy.port, "duckduckgo.com:443")
    server.close()
    await server.wait_closed()
    assert "proxy-authorization" not in _headers(record[0])


def test_the_proxy_record_does_not_show_its_credentials(monkeypatch):
    _proxy_url(monkeypatch, "http://user:s3cret@127.0.0.1:7899")
    chain = bp._upstream_proxy("duckduckgo.com")
    shown = f"{chain!r} {chain} {[chain]}"
    assert "127.0.0.1" in shown                                  # still says where it points
    assert "s3cret" not in shown and chain.auth.split()[1] not in shown


_MALFORMED_SETTINGS = [
    pytest.param("http://user:s3cret@127.0.0.1:notaport", id="bad-port"),
    pytest.param("http://user:s3cret@[::1", id="bad-ipv6"),
    # POSIX decodes an environment byte it cannot read to a lone surrogate, which UTF-8 refuses.
    pytest.param("http://user:s3cret\udcff@127.0.0.1:7899", id="undecodable-byte"),
    # urlsplit's own message quotes the whole netloc here, password included.
    pytest.param("http://user:s3cret\uff0f@127.0.0.1:7899", id="parser-quotes-the-netloc"),
    # No host, e.g. HTTPS_PROXY=http://$UNSET_VARIABLE:7899. Not an address: never "go direct".
    pytest.param("http://:7899", id="empty-host"),
    pytest.param("http://user:s3cret@:7899", id="empty-host-with-credentials"),
    pytest.param("http://", id="nothing-after-the-scheme"),
    # Port 0 is not a port anyone listens on; it must not be read as "no port", i.e. 80.
    pytest.param("http://127.0.0.1:0", id="port-zero"),
    pytest.param("http://user:s3cret@127.0.0.1:0", id="port-zero-with-credentials"),
    # Nothing readable before the "://", e.g. HTTPS_PROXY=$SCHEME://host:7899 with SCHEME unset.
    # Only a scheme that IS there and is not http is somebody else's proxy; this is a broken one.
    pytest.param("://127.0.0.1:7899", id="empty-scheme"),
    pytest.param("://user:s3cret@127.0.0.1:7899", id="empty-scheme-with-credentials"),
    pytest.param("ht tp://127.0.0.1:7899", id="unreadable-scheme"),
    # An '@' that is not in the netloc: here it is in the path, so urlsplit reads host "user"
    # and port 12345, the user name and the password's leading digits. And one in the query.
    pytest.param("http://user:12345/word@proxy:8080", id="at-sign-in-the-path"),
    pytest.param("http://proxy.invalid:8080/?user@x", id="at-sign-in-the-query"),
]


@pytest.mark.parametrize("bad", _MALFORMED_SETTINGS)
def test_a_malformed_proxy_value_is_refused_without_echoing_it(monkeypatch, bad):
    _proxy_url(monkeypatch, bad)
    with pytest.raises(ValueError, match="malformed") as caught:
        bp._upstream_proxy("duckduckgo.com")
    assert "s3cret" not in str(caught.value)
    # Not chained to the parser's error either: it holds the value, and anything that walks the
    # chain (a crash reporter, logging.exception) would print it.
    assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.mark.asyncio
async def test_the_bypass_list_is_asked_about_the_canonical_name(monkeypatch):
    """NO_PROXY and the system exception list are matched against the plain lower-case name:
    fnmatch is case-sensitive on macOS, so the page's spelling would miss `*.local`. An IPv6
    literal goes without its brackets."""
    asked: list[str] = []
    server, port = await _upstream([])
    _system_proxy(monkeypatch, port)
    monkeypatch.setattr(net_pin, "proxy_bypass", lambda host: asked.append(host) or False)
    _answers(monkeypatch, {"duckduckgo.com": "198.18.0.35"})
    async with bp.PublicTunnel() as proxy:
        assert b"200" in await _request(proxy.port, "DuckDuckGo.COM:443")
        assert b"200" in await _request(proxy.port, "[2001:4860:4860::8888]:443")
    server.close()
    await server.wait_closed()
    assert asked == ["duckduckgo.com", "2001:4860:4860::8888"]


@pytest.mark.asyncio
async def test_a_refusing_proxy_is_named_in_the_log(monkeypatch, caplog):
    server, port = await _upstream([], reply=b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
    _system_proxy(monkeypatch, port)
    _answers(monkeypatch, {"duckduckgo.com": "198.18.0.35"})
    async with bp.PublicTunnel() as proxy:
        with caplog.at_level(logging.DEBUG, logger=bp.logger.name):
            assert b"403" in await _request(proxy.port, "duckduckgo.com:443")
    server.close()
    await server.wait_closed()
    assert proxy.blocked == 1
    assert _tunnel_log(caplog, logging.WARNING)[-1] == (
        f"browser tunnel: upstream proxy 127.0.0.1:{port} refused a tunnel (HTTP 407); each "
        "refused name is logged at DEBUG")
    assert _tunnel_log(caplog, logging.DEBUG)[-1] == (
        f"browser tunnel: upstream proxy 127.0.0.1:{port} refused the tunnel to duckduckgo.com "
        "(HTTP 407)")


@pytest.mark.asyncio
async def test_a_dead_proxy_is_named_in_the_log_and_the_tunnel_stays_closed(monkeypatch, caplog):
    port = _dead_port()
    _system_proxy(monkeypatch, port)
    _answers(monkeypatch, {"duckduckgo.com": "93.184.216.34"})     # public: could be dialled direct
    dials = _dials(monkeypatch)
    async with bp.PublicTunnel() as proxy:
        with caplog.at_level(logging.WARNING, logger=bp.logger.name):
            assert b"403" in await _request(proxy.port, "duckduckgo.com:443")
    assert proxy.blocked == 1
    assert _tunnel_log(caplog)[-1] == (f"browser tunnel: upstream proxy 127.0.0.1:{port} "
                                       "unreachable (ConnectionRefusedError)")
    assert {host for host, _ in dials} == {"127.0.0.1"}              # no fallback to a direct dial


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", _MALFORMED_SETTINGS)
async def test_a_malformed_proxy_setting_is_named_and_refuses_the_tunnel(monkeypatch, caplog, bad):
    _proxy_url(monkeypatch, bad)
    _answers(monkeypatch, {"duckduckgo.com": "93.184.216.34"})     # public: could be dialled direct
    dials = _dials(monkeypatch)
    async with bp.PublicTunnel() as proxy:
        with caplog.at_level(logging.WARNING, logger=bp.logger.name):
            assert b"403" in await _request(proxy.port, "duckduckgo.com:443")
    assert proxy.blocked == 1
    assert _tunnel_log(caplog) == ["browser tunnel: the system proxy setting is malformed; "
                                   "every tunnel is refused until it is fixed"]
    assert {host for host, _ in dials} == {"127.0.0.1"}              # not a licence to go direct


@pytest.mark.asyncio
async def test_an_at_sign_outside_the_netloc_is_malformed_never_dialled_never_logged(
        monkeypatch, caplog):
    """`http://user:12345/word@proxy:8080` parsed as the proxy user:12345, and the log lines
    printed "user:12345": a user name and the start of a password. Refused as malformed."""
    _proxy_url(monkeypatch, "http://user:12345/word@proxy:8080")
    _answers(monkeypatch, {"duckduckgo.com": "198.18.0.35"})
    dials = _dials(monkeypatch)
    async with bp.PublicTunnel() as proxy:
        with caplog.at_level(logging.DEBUG):                  # every logger, every level
            assert b"403" in await _request(proxy.port, "duckduckgo.com:443")
    assert proxy.blocked == 1
    assert dials == [("127.0.0.1", proxy.port)]               # only our own way into the tunnel
    assert _tunnel_log(caplog) == ["browser tunnel: the system proxy setting is malformed; "
                                   "every tunnel is refused until it is fixed"]
    assert not any("12345" in record.getMessage() for record in caplog.records)
    assert "12345" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["accepted", "refused", "dead", "malformed",
                                      "malformed-netloc"])
async def test_credentials_never_reach_the_log(monkeypatch, caplog, scenario):
    secret = "s3cret-token"
    server = None
    if scenario == "malformed":
        url = f"http://user:{secret}@127.0.0.1:notaport"
    elif scenario == "malformed-netloc":
        url = f"http://user:{secret}\uff0f@127.0.0.1:7899"       # urlsplit's message quotes this
    else:
        if scenario == "dead":
            port = _dead_port()
        else:
            reply = (b"HTTP/1.1 200 Connection established\r\n\r\n" if scenario == "accepted"
                     else b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
            server, port = await _upstream([], reply=reply)
        url = f"http://user:{secret}@127.0.0.1:{port}"
    _proxy_url(monkeypatch, url)
    _answers(monkeypatch, {"duckduckgo.com": "198.18.0.35"})
    async with bp.PublicTunnel() as proxy:
        with caplog.at_level(logging.DEBUG):                  # every logger, every level
            await _request(proxy.port, "duckduckgo.com:443")
    if server is not None:
        server.close()
        await server.wait_closed()
    token = base64.b64encode(f"user:{secret}".encode()).decode("ascii")
    assert _tunnel_log(caplog)                  # the tunnel did speak, so the check means something
    assert secret not in caplog.text and token not in caplog.text
