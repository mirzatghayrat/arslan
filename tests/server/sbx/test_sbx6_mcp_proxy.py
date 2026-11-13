"""SBX-6 MCP proxy (v0.1.64): a declared MCP server reaches the network only through Arslan's local proxy.

- An installed server that declared the network runs in the commands' proxy mode: TCP only to `sandbox_proxy`'s
  port and to loopback, minus every port Arslan listens on and the system proxies' loopback ports, with no DNS
  and no UDP. Without a running proxy, or with Arslan's own ports unknown, it is offline. Any-declared is gone.
- It is told the proxy in its environment (and nothing else about proxies); an undeclared server is told nothing.
- The user's "Allow system certificate checks in the sandbox" grants the trust service in proxy mode only, as for
  commands.

The kernel gates for the `mcp-proxy` base are SBX-6p's (`test_sbx6_network.py`, `test_sbx6_settings.py`); the
macOS tests here start a server the product's way (`capability_sandbox.wrap`) against the real proxy.
"""
import asyncio
import errno
import json
import os
import re
import socket
import subprocess
import sys
import textwrap

import pytest

from server.services import capability_sandbox, command_sandbox, net_policy, sandbox_proxy, terminal_exec
from tests.server.sbx.profile_files import read_profile

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")
_TRUST = '(allow mach-lookup (global-name "com.apple.trustd.agent"))'
_PROXY_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_REFUSED = (errno.EPERM, errno.EACCES)


@pytest.fixture
def ports(monkeypatch):
    """Stand-ins for Arslan's own listening ports and this Mac's proxies, never this process's or this Mac's."""
    state = {"bound": [8741], "system": ["socks5://127.0.0.1:7891"]}
    monkeypatch.setattr(sandbox_proxy, "listening_ports", lambda: state["bound"])
    monkeypatch.setattr(sandbox_proxy, "system_proxies", lambda: list(state["system"]))
    return state


def _profile(tmp_path, *, network=True, **kw):
    return capability_sandbox.profile(root=tmp_path / "srv", folders=[], network=network, read=[], **kw)


# ── the profile ──────────────────────────────────────────────────────────────

def test_a_declared_server_gets_the_proxy_port_and_loopback_minus_arslans_ports(tmp_path, ports):
    text = _profile(tmp_path, proxy_port=41000)
    assert '(allow network-outbound (remote tcp "localhost:41000"))' in text
    assert '(allow network-outbound (remote tcp "localhost:*"))' in text          # local dev servers
    for port in (7891, 8741):
        assert f'(deny network-outbound (remote tcp "localhost:{port}"))' in text, port
    assert '(deny network-outbound (remote tcp "localhost:41000"))' not in text
    assert '"*:*"' not in text and "mDNSResponder" not in text and "trustd" not in text   # no other host, no DNS
    assert "(deny network*)" not in text


def test_without_a_proxy_or_with_arslans_ports_unknown_it_is_offline(tmp_path, ports):
    off = _profile(tmp_path, network=False)
    assert "(deny network*)" in off
    assert _profile(tmp_path) == off                                 # no proxy running
    ports["bound"] = None
    assert _profile(tmp_path, proxy_port=41000) == off               # Arslan's own ports unreadable: closed


def test_an_undeclared_server_stays_offline_even_with_a_proxy_running(tmp_path, ports):
    assert _profile(tmp_path, network=False, proxy_port=41000, trust_service=True) == _profile(tmp_path, network=False)


def test_the_trust_service_comes_only_with_the_setting_and_the_proxy(tmp_path, ports):
    assert _TRUST not in _profile(tmp_path, proxy_port=41000)                     # off by default
    on = _profile(tmp_path, proxy_port=41000, trust_service=True)
    assert _TRUST in on and on.count("(allow mach-lookup") == 2                   # FSEvents (closed again) and it
    assert _TRUST not in _profile(tmp_path, trust_service=True)                   # offline: never
    ports["bound"] = None
    assert _TRUST not in _profile(tmp_path, proxy_port=41000, trust_service=True)


# ── its environment ──────────────────────────────────────────────────────────

def _wrap(tmp_path, env, **sandbox):
    """(command, [profile text, *the rest of args], env, cwd): #813 review 11's `-f` file read back, so the checks
    below read the profile where `args[1]` was its text."""
    command, args, env, cwd = capability_sandbox.wrap("/bin/echo", [], env,
                                                      {"root": str(tmp_path / "srv"), "folders": [], **sandbox})
    return command, [args[0], read_profile(args), *args[2:]], env, cwd


def test_a_declared_server_is_told_only_arslans_proxy(tmp_path, ports):
    # A proxy address the server's own config or this Mac set, with a sign-in in it, does not reach the server:
    # the kernel would refuse it anyway, and Arslan's proxy goes upstream itself.
    inherited = {name: "http://someone:pw-for-this-test@127.0.0.1:7891" for name in _PROXY_NAMES}
    _, args, env, _ = _wrap(tmp_path, {"PATH": "/usr/bin", **inherited, "NO_PROXY": "corp.invalid"},
                            network=True, proxy_port=41000)
    for name in _PROXY_NAMES:
        assert env[name] == "http://127.0.0.1:41000", name
    assert env["NO_PROXY"] == env["no_proxy"] == "localhost,127.0.0.1,::1"
    assert env["NODE_USE_ENV_PROXY"] == "1"                         # Node 24's fetch reads the variables only then
    assert "pw-for-this-test" not in json.dumps(env)
    assert '(allow network-outbound (remote tcp "localhost:41000"))' in args[1]


def test_wrap_closes_arslans_ports_and_this_macs_proxies_itself(tmp_path, ports):
    """#771 review: started the product's way, a server's profile denies the ports Arslan listens on and every
    announced system proxy's loopback port, read by `wrap` (no caller passes them), so neither is a way round
    Arslan's proxy."""
    ports["system"] = ["http://127.0.0.1:7891", "socks5://someone:pw-for-this-test@[::1]:7892"]
    _, args, env, _ = _wrap(tmp_path, {"PATH": "/usr/bin"}, network=True, proxy_port=41000)
    for port in (8741, 7891, 7892):
        assert f'(deny network-outbound (remote tcp "localhost:{port}"))' in args[1], port
    assert '(allow network-outbound (remote tcp "localhost:41000"))' in args[1]
    assert "pw-for-this-test" not in json.dumps(env) + "".join(args)


@pytest.mark.parametrize("sandbox,known", [({"network": False, "proxy_port": 41000}, True), ({"network": True}, True),
                                           ({"network": True, "proxy_port": 41000}, False)],
                         ids=["undeclared", "no-proxy", "ports-unknown"])
def test_a_server_with_no_way_out_is_told_no_proxy(tmp_path, ports, sandbox, known):
    if not known:
        ports["bound"] = None              # #771 review: an unreadable port list is offline, never an empty one
    _, args, env, _ = _wrap(tmp_path, {"PATH": "/usr/bin"}, **sandbox)
    assert not {*_PROXY_NAMES, "NO_PROXY", "no_proxy", "NODE_USE_ENV_PROXY"} & set(env)
    assert "(deny network*)" in args[1]


# ── the session starts it with the running proxy ─────────────────────────────

async def test_the_session_passes_the_proxy_and_the_setting_to_a_declared_server_only(monkeypatch, tmp_path):
    from server.mcp import proxy_resolve, session

    class Stop(Exception):
        pass

    seen, started, setting = [], [], {"on": True}

    def wrap(command, args, env, sandbox):
        seen.append(dict(sandbox))
        raise Stop

    async def port():
        started.append(True)
        return 41000

    async def allowed():
        return setting["on"]
    monkeypatch.setattr(capability_sandbox, "wrap", wrap)
    monkeypatch.setattr(sandbox_proxy, "port", port)
    monkeypatch.setattr(terminal_exec, "trust_service_allowed", allowed)
    monkeypatch.setattr(proxy_resolve, "_scutil_proxy", dict)
    manager = session.MCPSessionManager()
    stored = []
    # Declared with the setting on, declared with it off (#771 review: the setting decides), undeclared.
    for network, on in ((True, True), (True, False), (False, True)):
        setting["on"] = on
        stored.append({"root": str(tmp_path / "srv"), "folders": [], "network": network})
        with pytest.raises(Stop):
            await manager._open_session({"id": 7, "command": "/bin/echo", "args": [], "env": {"PATH": "/usr/bin"},
                                         "sandbox": stored[-1]})
    assert seen[0]["proxy_port"] == 41000 and seen[0]["trust_service"] is True
    assert seen[1]["proxy_port"] == 41000 and seen[1]["trust_service"] is False
    assert seen[2].get("proxy_port") is None and not seen[2].get("trust_service")
    assert started == [True, True]                                   # no proxy is started for an undeclared one
    assert all("proxy_port" not in s and "trust_service" not in s for s in stored)   # the stored grant is unchanged


# ── what the kernel does with it (macOS, the real proxy) ─────────────────────

_PROBE = textwrap.dedent("""
    import base64, json, os, socket, sys
    proxy, ours, udp_port = (int(a) for a in sys.argv[1:4])

    def code(fn):
        try:
            return fn()
        except OSError as exc:
            return exc.errno

    def through_proxy():
        # NET-a: as its HTTP client would, with the credentials of the address it was told
        told = os.environ.get("HTTPS_PROXY") or "http://none:none@x"
        auth = base64.b64encode(told.split("//", 1)[1].split("@", 1)[0].encode()).decode()
        with socket.create_connection(("127.0.0.1", proxy), timeout=5) as s:
            s.sendall(("CONNECT 127.0.0.1:22 HTTP/1.1\\r\\nHost: x\\r\\nProxy-Authorization: Basic " + auth
                       + "\\r\\n\\r\\n").encode())
            return s.recv(64).split(b" ")[1].decode()

    def tcp(port):
        with socket.create_connection(("127.0.0.1", port), timeout=3):
            return 0

    def resolver():
        with socket.socket(socket.AF_UNIX) as s:
            s.connect("/private/var/run/mDNSResponder")
            return 0

    def udp():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(b"sbx", ("127.0.0.1", udp_port))
            return 0

    print(json.dumps({"told": os.environ.get("HTTPS_PROXY"), "proxy": code(through_proxy), "ours": code(lambda: tcp(ours)),
                      "resolver": code(resolver), "udp": code(udp)}))
""")


async def _start_probe(tmp_path, *, network):
    """Start the probe as the session starts a server (`wrap`), with this process standing for Arslan: its own
    listening ports, read by `lsof` as in the product, include `ours`. Only loopback is contacted."""
    root = tmp_path / "srv"
    root.mkdir(parents=True, exist_ok=True)
    (root / "probe.py").write_text(_PROBE)
    proxy_port = await sandbox_proxy.port()
    assert proxy_port
    with socket.socket() as ours, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        ours.bind(("127.0.0.1", 0))
        ours.listen(4)
        receiver.bind(("127.0.0.1", 0))
        python = os.path.realpath(sys.executable)
        sandbox = {"root": str(root), "folders": [], "network": network, "read": [os.path.realpath(sys.base_prefix)]}
        if network:
            sandbox["proxy_port"] = proxy_port
            sandbox["proxy_token"] = (await net_policy.start_run("probe", judged=False)).token    # as the session does
        command, args, env, cwd = await asyncio.to_thread(
            capability_sandbox.wrap, python,
            ["-I", str(root / "probe.py"), str(proxy_port), str(ours.getsockname()[1]), str(receiver.getsockname()[1])],
            {"PATH": "/usr/bin:/bin"}, sandbox)
        out = await asyncio.to_thread(subprocess.run, [command, *args], env=env, cwd=cwd, capture_output=True,
                                      text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return proxy_port, json.loads(out.stdout)


@pytest.mark.macos
@macos
async def test_a_declared_server_reaches_the_proxy_and_nothing_local_round_it(tmp_path):
    sandbox_proxy._reset_for_tests()
    try:
        port, seen = await _start_probe(tmp_path, network=True)
    finally:
        await sandbox_proxy.shutdown()
        net_policy._reset_for_tests()
    assert re.fullmatch(rf"http://[0-9a-f]{{32}}:sandbox@127\.0\.0\.1:{port}", seen["told"]), seen   # NET-a: its token
    assert seen["proxy"] == "403", seen               # reached, and the proxy refuses a loopback destination
    assert seen["ours"] in _REFUSED, seen             # one of Arslan's own ports
    assert seen["resolver"] in _REFUSED, seen         # no DNS of its own
    assert seen["udp"] in _REFUSED, seen              # no UDP


@pytest.mark.macos
@macos
async def test_an_undeclared_server_reaches_nothing(tmp_path):
    sandbox_proxy._reset_for_tests()
    try:
        _, seen = await _start_probe(tmp_path, network=False)
    finally:
        await sandbox_proxy.shutdown()
    assert seen["told"] is None, seen
    for name in ("proxy", "ours", "resolver", "udp"):
        assert seen[name] in _REFUSED, (name, seen)
