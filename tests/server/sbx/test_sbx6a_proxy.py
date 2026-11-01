"""SBX-6a (v0.1.64, the user's N-a): online commands reach the network only through Arslan's local proxy.

- The commands profile in proxy mode allows the proxy's loopback port plus loopback for dev servers, minus
  every port Arslan itself listens on and the system proxies' loopback ports (`excluded_ports`).
- Any-declared is retired for commands; online without a running proxy, or without knowing Arslan's own
  ports, is offline (fail closed).
- The proxy speaks CONNECT and plain-http forwarding, with no site list. Every destination must resolve to
  public addresses (`net_pin`), so it is no way round the kernel to Arslan's ports or the LAN.

Whether what should be denied is denied under real seatbelt is SBX-6p's (Codex).
"""
import asyncio
from contextlib import suppress
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.registry.net_pin import _BlockedHost
from server.services import command_sandbox, sandbox_proxy, terminal_exec
from server.services.sandbox_profile import NetworkMode

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")


# ── the ports proxy mode refuses on loopback ─────────────────────────────────

def test_the_system_proxies_loopback_ports_and_arslans_own_are_excluded_but_not_the_proxy():
    proxies = ["http://localhost:7890", "socks5://[::1]:1080", "https://127.0.0.1", "http://10.0.0.1:3128",
               "127.0.0.1:8118", "socks5h://localhost"]
    assert sandbox_proxy.excluded_ports([8741, 52000, 40000], proxies, proxy_port=40000) == (
        443, 1080, 7890, 8118, 8741, 52000)


def test_a_system_proxy_on_the_proxys_own_port_is_refused():
    """SBX-6p review: an IPv4 and an IPv6 listener can share a port number, and a port rule allows both."""
    with pytest.raises(ValueError, match="proxy port.*system proxy"):
        sandbox_proxy.excluded_ports([], ["http://127.0.0.1:7890", "socks5://[::1]:40000"], proxy_port=40000)


async def test_the_proxy_moves_off_a_port_a_system_proxy_takes(monkeypatch):
    sandbox_proxy._reset_for_tests()
    taken = []
    monkeypatch.setattr(sandbox_proxy, "system_proxies", lambda: [f"http://[::1]:{p}" for p in taken])
    try:
        first = await sandbox_proxy.port()
        taken.append(first)
        second = await sandbox_proxy.port()
        assert second != first and isinstance(second, int)
    finally:
        await sandbox_proxy.shutdown()


def test_every_system_proxy_is_excluded_in_the_profile(home):
    text = command_sandbox.commands_profile(home / "ws", proxy_port=41000, bound_ports=[], system_proxies=[
        "http://127.0.0.1:7890", "https://localhost:7891", "socks5://[::1]:7892"])
    for port in (7890, 7891, 7892):
        assert f'(deny network-outbound (remote tcp "localhost:{port}"))' in text, port


def test_a_broken_proxy_setting_is_skipped_not_fatal():
    assert sandbox_proxy.excluded_ports([], ["http://localhost:notaport", "::::", ""], proxy_port=1) == ()


def test_arslans_listening_ports_come_from_lsof(monkeypatch):
    out = "p123\nf3\nn127.0.0.1:8741\nf9\nn[::1]:52591\nf11\nn*:4000\n"
    monkeypatch.setattr(sandbox_proxy.subprocess, "run",
                        lambda argv, **kw: SimpleNamespace(returncode=0, stdout=out, stderr=""))
    assert sandbox_proxy.listening_ports() == [4000, 8741, 52591]


@pytest.mark.parametrize("failure", ["missing", "exit", "garbage"])
def test_unknown_listening_ports_are_none(monkeypatch, failure):
    def run(argv, **kw):
        if failure == "missing":
            raise FileNotFoundError(argv[0])
        if failure == "exit":
            return SimpleNamespace(returncode=1, stdout="", stderr="lsof: no")
        return SimpleNamespace(returncode=0, stdout="p1\nnlocalhost:http\n", stderr="")
    monkeypatch.setattr(sandbox_proxy.subprocess, "run", run)
    assert sandbox_proxy.listening_ports() is None


def test_the_system_proxies_are_read_from_the_environment_and_scutil(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:7897")
    monkeypatch.setattr(sandbox_proxy, "_scutil", lambda: (
        "<dictionary> {\n  HTTPEnable : 1\n  HTTPPort : 7890\n  HTTPProxy : 127.0.0.1\n"
        "  SOCKSEnable : 1\n  SOCKSPort : 7891\n  SOCKSProxy : localhost\n"
        "  HTTPSEnable : 0\n  HTTPSPort : 9999\n  HTTPSProxy : 127.0.0.1\n}\n"))
    assert sandbox_proxy.system_proxies() == ["http://127.0.0.1:7897", "http://127.0.0.1:7890",
                                              "socks5://localhost:7891"]


# ── the commands profile in proxy mode ───────────────────────────────────────

@pytest.fixture
def home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    (home / "ws").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def test_online_is_the_proxy_port_and_loopback_minus_arslans_ports(home):
    text = command_sandbox.commands_profile(home / "ws", proxy_port=41000, bound_ports=[8741, 41000, 52000],
                                            system_proxies=["http://127.0.0.1:7890"])
    assert '(allow network-outbound (remote tcp "localhost:41000"))' in text
    assert '(allow network-outbound (remote tcp "localhost:*"))' in text
    assert '"*:*"' not in text and "mDNSResponder" not in text            # no DNS, no other host
    for port in (7890, 8741, 52000):
        assert f'(deny network-outbound (remote tcp "localhost:{port}"))' in text
    assert '(deny network-outbound (remote tcp "localhost:41000"))' not in text
    assert "(deny network-bind network-inbound)" in text                  # D1 stands


def test_any_declared_is_retired_for_commands(home):
    with pytest.raises(ValueError, match="any-declared"):
        command_sandbox.commands_profile(home / "ws", network=NetworkMode.ANY_DECLARED)


def test_online_with_no_proxy_or_unknown_ports_is_offline(home, monkeypatch):
    offline = command_sandbox.commands_profile(home / "ws", offline=True)
    assert command_sandbox.commands_profile(home / "ws") == offline                  # no proxy port
    monkeypatch.setattr(sandbox_proxy, "listening_ports", lambda: None)
    assert command_sandbox.commands_profile(home / "ws", proxy_port=41000, system_proxies=[]) == offline
    assert "(deny network*)" in offline


def test_the_product_reads_arslans_ports_and_the_system_proxies_itself(home, monkeypatch):
    monkeypatch.setattr(sandbox_proxy, "listening_ports", lambda: [8741, 41000])
    monkeypatch.setattr(sandbox_proxy, "system_proxies", lambda: ["socks5://[::1]:7891"])
    text = command_sandbox.commands_profile(home / "ws", proxy_port=41000)
    assert '(deny network-outbound (remote tcp "localhost:8741"))' in text
    assert '(deny network-outbound (remote tcp "localhost:7891"))' in text


def test_the_sbx_harness_registers_the_proxy_bases():
    from tests.server.sbx.harness import BUILT_BASES
    assert {"commands-proxy", "network-sbx6"} <= set(BUILT_BASES)
    assert not {"mcp-proxy", "run-python"} & set(BUILT_BASES)          # SBX-4a's surfaces, still pending


# ── the run: its environment points at the proxy ─────────────────────────────

async def test_an_online_sandboxed_run_gets_the_proxy_in_its_environment(monkeypatch, tmp_path):
    seen = {}

    async def port():
        return 41000

    def wrapper(cwd, **kw):
        seen.update(kw)
        return ["/usr/bin/env"]
    monkeypatch.setattr(sandbox_proxy, "port", port)
    monkeypatch.setattr(command_sandbox, "wrapper", wrapper)
    result = await terminal_exec.run("env", cwd=tmp_path, sandbox=True)
    assert seen["proxy_port"] == 41000
    lines = set(result["stdout"].splitlines())
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        assert f"{name}=http://127.0.0.1:41000" in lines, name
    assert "NO_PROXY=localhost,127.0.0.1,::1" in lines


async def test_an_offline_run_gets_no_proxy(monkeypatch, tmp_path):
    seen = {}

    async def port():
        raise AssertionError("no proxy is started for an offline run")

    def wrapper(cwd, **kw):
        seen.update(kw)
        return ["/usr/bin/env"]
    monkeypatch.setattr(sandbox_proxy, "port", port)
    monkeypatch.setattr(command_sandbox, "wrapper", wrapper)
    result = await terminal_exec.run("env", cwd=tmp_path, sandbox=True, offline=True)
    assert seen.get("proxy_port") is None and "HTTPS_PROXY=" not in result["stdout"]


# ── the proxy itself ─────────────────────────────────────────────────────────

@pytest.fixture
async def origin():
    """A stand-in for a public server: echoes what it got, then closes."""
    got = []

    async def serve(reader, writer):
        data = await reader.read(65536)
        got.append(data)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    yield server.sockets[0].getsockname()[1], got
    server.close()
    await server.wait_closed()


@pytest.fixture
async def proxy(monkeypatch):
    monkeypatch.setattr(sandbox_proxy.browser_proxy.net_pin, "getproxies", lambda: {})
    p = sandbox_proxy.LocalProxy()
    await p.start()
    yield p
    await p.close()


def _pin_to(monkeypatch, port, seen):
    def resolve(url, **kw):
        seen.append(url)
        return "127.0.0.1", "example.com", port
    monkeypatch.setattr(sandbox_proxy, "_resolve_pinned", resolve)


async def _ask(proxy_port, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    writer.write(request)
    await writer.drain()
    data = await asyncio.wait_for(reader.read(65536), 5)
    if data.startswith(b"HTTP/1.1 200 Connection Established"):
        writer.write(b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n")
        await writer.drain()
        data += await asyncio.wait_for(reader.read(65536), 5)
    writer.close()
    return data


async def test_the_proxy_listens_on_loopback_only(proxy):
    assert proxy.server.sockets and all(s.getsockname()[0] == "127.0.0.1" for s in proxy.server.sockets)


@pytest.mark.parametrize("target", [b"10.0.0.1:443", b"169.254.169.254:80", b"[::1]:8741", b"localhost:22"])
async def test_net_pins_own_judgement_refuses_a_non_public_target(proxy, target):
    """Unmocked: the resolver itself refuses private, link-local and loopback destinations."""
    reply = await _ask(proxy.port, b"CONNECT " + target + b" HTTP/1.1\r\nHost: x\r\n\r\n")
    assert reply.startswith(b"HTTP/1.1 403 Forbidden"), reply


async def test_too_many_connections_are_refused(proxy, origin, monkeypatch):
    _pin_to(monkeypatch, origin[0], [])                           # uncapped, this tunnel would open
    monkeypatch.setattr(sandbox_proxy, "_CONNECTIONS", 0)
    reply = await _ask(proxy.port, b"CONNECT example.com:443 HTTP/1.1\r\nHost: x\r\n\r\n")
    assert reply.startswith(b"HTTP/1.1 403 Forbidden"), reply


async def test_an_idle_tunnel_is_closed(proxy, origin, monkeypatch):
    port, _ = origin
    _pin_to(monkeypatch, port, [])
    monkeypatch.setattr(sandbox_proxy, "_IDLE_S", 0.2)
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
    writer.write(b"CONNECT example.com:443 HTTP/1.1\r\nHost: x\r\n\r\n")
    await writer.drain()
    assert (await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)).startswith(b"HTTP/1.1 200")
    assert await asyncio.wait_for(reader.read(), 5) == b""        # closed without a byte from either side
    writer.close()


async def test_a_quiet_client_is_not_cut_off_while_the_server_talks(proxy, monkeypatch):
    """One idle clock for both directions: the client stays quiet past the idle limit while the server
    streams, and its next bytes still arrive."""
    got = asyncio.get_running_loop().create_future()

    async def serve(reader, writer):
        for _ in range(8):
            writer.write(b".")
            await writer.drain()
            await asyncio.sleep(0.05)
        got.set_result(await reader.read(4))
        writer.close()
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    _pin_to(monkeypatch, server.sockets[0].getsockname()[1], [])
    monkeypatch.setattr(sandbox_proxy, "_IDLE_S", 0.2)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
        writer.write(b"CONNECT example.com:443 HTTP/1.1\r\nHost: x\r\n\r\n")
        await writer.drain()
        await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        await asyncio.sleep(0.35)                                   # quiet past the limit, the server not
        writer.write(b"ping")
        await writer.drain()
        assert await asyncio.wait_for(got, 5) == b"ping"
        writer.close()
    finally:
        server.close()


async def _settles(proxy, seconds: float) -> bool:
    for _ in range(int(seconds / 0.05)):
        if not proxy.tasks:
            return True
        await asyncio.sleep(0.05)
    return not proxy.tasks


@pytest.mark.parametrize("client_sends", [False, True], ids=["half-closed-client", "neither-side-reads"])
async def test_a_peer_that_stops_reading_loses_its_slot(proxy, monkeypatch, client_sends):
    """A client that half-closes and never reads a large reply, or two sides that both stop reading, can't
    hold a slot past the idle limit: drain() is bounded too."""
    async def serve(reader, writer):
        writer.write(b"x" * (16 << 20))                     # far more than the socket buffers hold
        with suppress(Exception):
            await writer.drain()
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    _pin_to(monkeypatch, server.sockets[0].getsockname()[1], [])
    monkeypatch.setattr(sandbox_proxy, "_IDLE_S", 0.3)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
        writer.write(b"CONNECT example.com:443 HTTP/1.1\r\nHost: x\r\n\r\n")
        await writer.drain()
        await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        if client_sends:
            writer.write(b"y" * (16 << 20))                 # the server never reads it
        else:
            writer.write_eof()
        assert await _settles(proxy, 3.0), "the slot is still held"
        writer.transport.abort()
    finally:
        server.close()


async def test_connect_relays_to_the_resolved_public_address(proxy, origin, monkeypatch):
    port, got = origin
    seen = []
    _pin_to(monkeypatch, port, seen)
    reply = await _ask(proxy.port, b"CONNECT example.com:8443 HTTP/1.1\r\nHost: example.com:8443\r\n\r\n")
    assert reply.startswith(b"HTTP/1.1 200 Connection Established\r\n\r\n") and reply.endswith(b"ok")
    assert seen == ["https://example.com:8443/"] and got[0].startswith(b"GET / HTTP/1.1")


async def test_plain_http_is_forwarded_in_origin_form_and_closed_after(proxy, origin, monkeypatch):
    port, got = origin
    seen = []
    _pin_to(monkeypatch, port, seen)
    reply = await _ask(proxy.port, b"GET http://example.com/a?b=1 HTTP/1.1\r\nHost: example.com\r\n"
                                   b"Proxy-Connection: keep-alive\r\nProxy-Authorization: x\r\n\r\n")
    assert reply.endswith(b"ok") and seen == ["http://example.com:80/"]
    head = got[0].decode()
    assert head.startswith("GET /a?b=1 HTTP/1.1\r\n") and "Connection: close\r\n" in head
    assert "Proxy-" not in head


@pytest.mark.parametrize("request_line", [
    b"CONNECT 127.0.0.1:8741 HTTP/1.1",          # refused by the resolver: not public
    b"GET http://192.168.1.2/ HTTP/1.1",
    b"GET /relative HTTP/1.1",                    # not a proxy request
    b"GET ftp://example.com/ HTTP/1.1",
    b"CONNECT example.com HTTP/1.1",              # no port
    b"CONNECT example.com:0 HTTP/1.1",
])
async def test_what_the_proxy_refuses(proxy, monkeypatch, request_line):
    def resolve(url, **kw):
        raise _BlockedHost("not public")
    monkeypatch.setattr(sandbox_proxy, "_resolve_pinned", resolve)
    reply = await _ask(proxy.port, request_line + b"\r\nHost: x\r\n\r\n")
    assert reply.startswith(b"HTTP/1.1 403 Forbidden"), reply


async def test_it_chains_through_a_system_http_proxy_by_name(monkeypatch, origin):
    port, got = origin
    seen = []
    monkeypatch.setattr(sandbox_proxy.browser_proxy.net_pin, "getproxies", lambda: {"https": f"http://127.0.0.1:{port}"})
    monkeypatch.setattr(sandbox_proxy.browser_proxy.net_pin, "proxy_bypass", lambda host: False)
    monkeypatch.setattr(sandbox_proxy, "_resolve_pinned",
                        lambda url, **kw: seen.append((url, kw)) or ("198.18.0.9", "example.com", 443))
    p = sandbox_proxy.LocalProxy()
    await p.start()
    try:
        await _ask(p.port, b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
    finally:
        await p.close()
    assert seen == [("https://example.com:443/", {"via_proxy": True})]
    assert got[0].startswith(b"CONNECT example.com:443 HTTP/1.1\r\n")


async def test_port_starts_one_proxy_and_reuses_it():
    sandbox_proxy._reset_for_tests()
    try:
        first = await sandbox_proxy.port()
        assert isinstance(first, int) and first == await sandbox_proxy.port()
    finally:
        await sandbox_proxy.shutdown()


# ── what should run does run (macOS) ─────────────────────────────────────────

@pytest.mark.macos
@macos
async def test_a_sandboxed_command_reaches_the_proxy_and_nothing_local_through_it(tmp_path):
    """The proxy's port is open to a sandboxed command, and the proxy refuses a loopback destination."""
    sandbox_proxy._reset_for_tests()
    try:
        result = await terminal_exec.run(
            "python3 -c \"import os, socket; p = int(os.environ['HTTPS_PROXY'].rsplit(':', 1)[1]); "
            "s = socket.create_connection(('127.0.0.1', p)); "
            "s.sendall(b'CONNECT 127.0.0.1:22 HTTP/1.1\\r\\nHost: x\\r\\n\\r\\n'); print(s.recv(30))\"",
            cwd=tmp_path, sandbox=True)
    finally:
        await sandbox_proxy.shutdown()
    assert result["sandbox"] == "workspace" and result["ok"], result
    assert "403 Forbidden" in result["stdout"]
