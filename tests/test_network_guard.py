"""The suite-wide network guard: ``_no_real_network_off_loopback`` in tests/conftest.py.

WHY IT EXISTS. Hermeticity used to hold only for a CORRECT implementation. A test of the web tools
replaced the resolver and the transport with fakes, and code that went AROUND a fake (a mutant, or
a regression) reached this Mac's real system proxy (127.0.0.1:7899, which forwards to the
internet) and its real, fake-IP DNS. A review mutation run sent about 250 real GETs that way
before it was caught. The guard makes that impossible from outside any single test file: it holds
whatever a test patches or forgets to patch.

WHAT IT REFUSES, for every test (the file's tests are the exact list):
 - ``socket.getaddrinfo`` of any NAME but ``localhost``. An address literal needs no network to
   "resolve" and is ANSWERED, so the code under test judges it itself. (It used to be refused, and
   three SSRF tests then passed because the lookup failed, not because net_pin judged the private
   address: switch the private-address check off and they stayed green.)
 - ``socket.socket.connect`` / ``connect_ex`` to an address that is not loopback. That is the path
   under asyncio (``open_connection``, ``sock_connect``), ``socket.create_connection``, urllib,
   http.client and httpcore. Unix sockets and loopback stay open: tests serve from this process and
   from subprocesses (test_profile_activation), so a rule on loopback ports would refuse them.
 - a request by a REAL httpx transport to a host that is not loopback, or through a PROXY, a loopback
   one included: the system proxy listens on 127.0.0.1.
 - the proxy ENVIRONMENT: HTTP(S)_PROXY and ALL_PROXY are removed and NO_PROXY=* is set. With no
   proxy variable at all (pytest launched from an IDE) urllib on macOS falls back to the SYSTEM
   proxy, and a real client would send even its loopback requests there.
Every refusal is RECORDED, and a test that provoked one it did not expect fails at teardown: a code
path that swallows the refusal (``github_eval.fetch_file`` does) is a silent leak. A test that
refuses on purpose carries ``network_refusals_expected`` (this whole file), and the opt-in live
runners are marked ``real_network`` BY PATH in conftest (they are historical acceptance evidence,
some frozen by digest, so the files stay as they were); the marker lifts the guard and nothing else.

NOT covered, and said so: UDP ``sendto``, ``gethostbyname``, and raw loopback sockets to a port that
is not the test's. It is a net under the fakes, not a sandbox.

These tests aim only at targets that are safe even if the guard were broken: ``.invalid`` names
(RFC 6761, never delegated), 0.0.0.1 for TCP (it fails locally, "No route to host", with no packet),
192.0.2.1 and 2001:db8::1 for UDP (``connect`` on a datagram socket sends nothing), loopback ports
that nothing listens on.
"""
from __future__ import annotations

import asyncio
import errno
import os
import re
import socket
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import httpx
import pytest

from server.registry import net_pin

pytestmark = pytest.mark.network_refusals_expected          # this file provokes the guard on purpose

REPO = Path(__file__).resolve().parents[1]

#: What the standard library and httpx are before any fixture runs (collection imports this module
#: first), to tell a lifted guard from an installed one.
REAL_GETADDRINFO = socket.getaddrinfo
REAL_CONNECT = socket.socket.connect
REAL_CONNECT_EX = socket.socket.connect_ex
REAL_ASYNC = httpx.AsyncHTTPTransport.handle_async_request
REAL_SYNC = httpx.HTTPTransport.handle_request

_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")

#: The opt-in runners that call a model API or public pages when their own environment opt-in is set.
#: The same nine paths as `_REAL_NETWORK_RUNNERS` in tests/conftest.py, which this file holds to.
LIVE_RUNNERS = [
    "tests/server/test_escalation_eval.py",
    "tests/server/test_stable_document_live.py",
    "tests/server/test_stable_memory_live.py",
    "tests/server/test_stable_research_live.py",
    "tests/server/test_stable_four_live.py",
    "tests/server/test_stable_release_live.py",
    "tests/server/test_stable_retest_live.py",
    "tests/server/test_stable_two_live.py",
    "tests/server/test_stage2_live.py",
]


@pytest.fixture
def no_connect(monkeypatch):
    """Refuse (and record) any real ``connect``: a transport guard that fails must not reach a wire.
    It also takes the socket-level guard out of the way, so that only the transport guard can
    produce "test guard" in the tests that use it."""
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


# ------------------------------------------------------------------ names, and address literals


@pytest.mark.parametrize("host", ["guard-selftest.invalid", b"guard-selftest.invalid",
                                  "app.localhost", "127.0.0.1.example.com", "LOCALHOST.example"])
def test_a_lookup_of_a_name_is_refused(host):
    """Any name but exactly `localhost`: `*.localhost` is a name too, and a resolver may send it
    out."""
    with pytest.raises(socket.gaierror, match="test guard"):
        socket.getaddrinfo(host, 443)


@pytest.mark.parametrize("host", ["192.0.2.1", "2001:db8::1", "93.184.216.34", "169.254.169.254",
                                  "10.0.0.1", b"192.0.2.1"])
def test_an_address_literal_needs_no_network_and_is_answered(host):
    assert socket.getaddrinfo(host, 80)


@pytest.mark.parametrize("literal", ["169.254.169.254", "192.168.1.8", "10.0.0.1", "100.64.1.1"])
def test_net_pin_judges_a_private_literal_itself(literal):
    """The wrong-reason bug: with the lookup refused, net_pin raised `cannot resolve` and never
    reached its private-address check. It must be the check that refuses."""
    with pytest.raises(net_pin._BlockedHost, match="private or internal address") as caught:
        net_pin._resolve_pinned(f"http://{literal}/")
    assert not isinstance(caught.value, net_pin._Unresolvable)


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


# ------------------------------------------------------------------ sockets: connect and connect_ex


@pytest.mark.parametrize("host", ["192.0.2.1", "93.184.216.34", "169.254.169.254", "10.0.0.1",
                                  "2001:db8::1"])
def test_a_connect_off_loopback_is_refused(host):
    """A datagram socket: its connect() sends nothing, so even a broken guard puts nothing on a wire
    here. The guard judges the address, not the socket type."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        with pytest.raises(OSError, match="test guard"):
            sock.connect((host, 9))
        assert sock.connect_ex((host, 9)) == errno.ENETUNREACH


def test_socket_create_connection_off_loopback_is_refused():
    with pytest.raises(OSError, match="test guard"):
        socket.create_connection(("0.0.0.1", 80), timeout=0.5)


async def test_the_asyncio_paths_go_through_the_same_rule():
    """`open_connection`, `sock_connect` and `create_connection` all end in `socket.socket.connect`."""
    with pytest.raises(OSError, match="test guard"):
        await asyncio.wait_for(asyncio.open_connection("0.0.0.1", 80), 2)
    loop = asyncio.get_running_loop()
    sock = socket.socket()
    sock.setblocking(False)
    try:
        with pytest.raises(OSError, match="test guard"):
            await asyncio.wait_for(loop.sock_connect(sock, ("0.0.0.1", 80)), 2)
    finally:
        sock.close()
    with pytest.raises(OSError, match="test guard"):
        await asyncio.wait_for(loop.create_connection(asyncio.Protocol, "0.0.0.1", 80), 2)


def test_a_connect_to_loopback_still_works():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass
        with socket.socket() as client:
            assert client.connect_ex(("127.0.0.1", port)) == 0


def test_a_unix_socket_connect_still_works():
    with tempfile.TemporaryDirectory(prefix="ng") as folder:         # short: sun_path is 104 bytes
        path = os.path.join(folder, "s")
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(path)
            server.listen()
            with socket.socket(socket.AF_UNIX) as client:
                client.connect(path)


# ------------------------------------------------------------------ the proxy environment


def test_the_proxy_environment_is_scrubbed():
    for var in _PROXY_VARS:
        assert var not in os.environ, var
    assert os.environ["NO_PROXY"] == "*" and os.environ["no_proxy"] == "*"
    # what a client built from the environment sees: no proxy, and not the macOS system proxy either
    assert urllib.request.getproxies() == {"no": "*"}
    assert urllib.request.proxy_bypass("example.com")


async def test_a_client_built_from_the_environment_reaches_loopback_directly():
    """The oauth-loopback and kernel-bench tests: `httpx.AsyncClient()` with trust_env, talking to a
    server in this process."""
    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            assert (await client.get(f"http://127.0.0.1:{port}/")).text == "ok"
    finally:
        server.close()
        await server.wait_closed()


def _child(tmp_path, source, *, proxy_env=None, args=()):
    """A child pytest session with the root conftest loaded as a plugin (the test file lives outside
    tests/), a temp HOME, the repo's own pytest config, and exactly the proxy variables given."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    test_file = tmp_path / "child" / "test_child.py"
    test_file.parent.mkdir(exist_ok=True)
    test_file.write_text(source)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("ARSLAN_", "PYTEST_")) and key not in _PROXY_VARS
           and key not in ("NO_PROXY", "no_proxy")}
    env.update(HOME=str(home), ARSLAN_SECRET_KEY="ci-secret", ARSLAN_API_TOKEN="",
               ARSLAN_DATA_DIR="data", **(proxy_env or {}))
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "tests.conftest",
         "-c", str(REPO / "pyproject.toml"), "--rootdir", str(REPO),
         "-W", "error::pytest.PytestUnknownMarkWarning", "-rA", *args, str(test_file)],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=110)


_SCRUBBED = '''
import os
import urllib.request


def test_the_child_sees_a_scrubbed_environment():
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        assert var not in os.environ, var
    assert os.environ["NO_PROXY"] == "*" and os.environ["no_proxy"] == "*"
    assert urllib.request.getproxies() == {"no": "*"}
'''


@pytest.mark.parametrize("launch", [
    pytest.param({"HTTP_PROXY": "http://127.0.0.1:7899", "HTTPS_PROXY": "http://127.0.0.1:7899",
                  "ALL_PROXY": "socks5://127.0.0.1:7899",
                  "NO_PROXY": "localhost,127.0.0.1,::1,.local"}, id="a-shell-with-the-proxy-exported"),
    pytest.param({}, id="an-IDE-with-no-proxy-variable-at-all"),
])
def test_the_scrub_does_not_depend_on_how_pytest_was_launched(tmp_path, launch):
    proc = _child(tmp_path, _SCRUBBED, proxy_env=launch)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-1500:]
    assert "PASSED" in proc.stdout and "ERROR" not in proc.stdout, proc.stdout[-3000:]


# ------------------------------------------------------------------ recording, and the loud teardown


def test_every_refusal_is_recorded(network_refusals):
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("guard-selftest.invalid", 80)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        with pytest.raises(OSError):
            sock.connect(("192.0.2.1", 9))
        sock.connect_ex(("192.0.2.2", 9))
    assert network_refusals == ["lookup of 'guard-selftest.invalid'", "connect to '192.0.2.1'",
                                "connect_ex to '192.0.2.2'"]


async def test_transport_refusals_are_recorded_too(network_refusals, own_resolver, no_connect):
    async with httpx.AsyncClient(trust_env=False, timeout=1) as client:
        with pytest.raises(httpx.ConnectError):
            await client.get("http://192.0.2.1/")
    async with httpx.AsyncClient(proxy="http://127.0.0.1:9", trust_env=False, timeout=1) as client:
        with pytest.raises(httpx.ConnectError):
            await client.get("http://127.0.0.1:1/")
    assert network_refusals == ["HTTP transport to '192.0.2.1'", "HTTP transport through a proxy"]


_TEARDOWN = '''
import socket

import pytest


def _swallowed():
    try:
        socket.getaddrinfo("api.example.invalid", 443)
    except OSError:
        pass                                     # the code under test swallows it, as fetch_file did


def test_swallows_a_refusal_it_did_not_expect():
    _swallowed()


@pytest.mark.network_refusals_expected
def test_expects_the_refusal():
    _swallowed()


@pytest.mark.real_network
def test_a_live_runner_is_not_guarded():
    assert socket.getaddrinfo.__name__ == "getaddrinfo"


def test_a_unit_test_is_guarded():
    assert socket.getaddrinfo.__name__ == "lookup"


def test_that_provokes_nothing():
    socket.getaddrinfo("127.0.0.1", 80)
'''


def test_a_refusal_the_test_did_not_expect_fails_it_at_teardown(tmp_path):
    proc = _child(tmp_path, _TEARDOWN)
    out = proc.stdout
    assert proc.returncode != 0, out[-3000:]
    # (the child's file lives outside the repo, so pytest prints its node ids with no path: match the tail)
    errors = re.findall(r"^ERROR \S*::(\w+)", out, re.M)
    assert errors == ["test_swallows_a_refusal_it_did_not_expect"], (errors, out[-3000:])
    passed = set(re.findall(r"^PASSED \S*::(\w+)", out, re.M))
    assert passed == {"test_swallows_a_refusal_it_did_not_expect", "test_expects_the_refusal",
                      "test_a_live_runner_is_not_guarded", "test_a_unit_test_is_guarded",
                      "test_that_provokes_nothing"}, (passed, out[-3000:])
    assert "api.example.invalid" in out and "did not expect" in out, out[-3000:]
    for hint in ("real_network", "network_refusals_expected"):
        assert hint in out, (hint, out[-3000:])               # the message says what to do


@pytest.mark.real_network
def test_real_network_lifts_the_guard_and_nothing_else(network_refusals):
    assert socket.getaddrinfo is REAL_GETADDRINFO
    assert socket.socket.connect is REAL_CONNECT
    assert socket.socket.connect_ex is REAL_CONNECT_EX
    assert httpx.AsyncHTTPTransport.handle_async_request is REAL_ASYNC
    assert httpx.HTTPTransport.handle_request is REAL_SYNC
    assert network_refusals == []


def test_an_unmarked_test_has_all_of_them_patched():
    assert socket.getaddrinfo is not REAL_GETADDRINFO
    assert socket.socket.connect is not REAL_CONNECT
    assert socket.socket.connect_ex is not REAL_CONNECT_EX
    assert httpx.AsyncHTTPTransport.handle_async_request is not REAL_ASYNC
    assert httpx.HTTPTransport.handle_request is not REAL_SYNC


def test_every_live_runner_carries_the_real_network_marker(request):
    """The nine opt-in runners that call a model API or public pages are marked by path in conftest,
    and that list is exactly this one: no runner missing, no other file in it, none renamed away.
    `-m real_network` then selects what pytest itself sees on each item, skipped ones included."""
    conftest = next(plugin for plugin in request.config.pluginmanager.get_plugins()
                    if str(getattr(plugin, "__file__", "")).endswith("tests/conftest.py"))
    assert sorted(conftest._REAL_NETWORK_RUNNERS) == sorted(LIVE_RUNNERS)
    assert len(set(conftest._REAL_NETWORK_RUNNERS)) == len(conftest._REAL_NETWORK_RUNNERS)
    for relative in LIVE_RUNNERS:
        assert (REPO / relative).is_file(), relative
    env = {key: value for key, value in os.environ.items() if not key.startswith(("ARSLAN_", "PYTEST_"))}
    env.update(ARSLAN_SECRET_KEY="ci-secret", ARSLAN_SECRET_KEY_FILE="")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         "-m", "real_network", *LIVE_RUNNERS],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=110)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-1500:]
    collected = {line.split("::")[0] for line in proc.stdout.splitlines() if "::" in line}
    assert collected == set(LIVE_RUNNERS), sorted(set(LIVE_RUNNERS) ^ collected)


# ------------------------------------------------------------------ real httpx transports


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
