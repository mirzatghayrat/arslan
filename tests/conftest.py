"""Shared pytest fixtures for the Arslan test suite."""
import os

# Keep the dev secret auto-generation (server.secret_bootstrap) DISABLED suite-wide:
# set-but-empty ARSLAN_SECRET_KEY_FILE means "never read/write any secret file".
# Without this, any test that reloads server.config with ARSLAN_SECRET_KEY unset would
# mint a real key file in the developer's ~/.arslan. Must execute before any server.*
# import (the frozen settings singleton builds at first import); this root conftest
# loads before every test module and sub-conftest. Tests that exercise the feature
# opt back in by pointing ARSLAN_SECRET_KEY_FILE at a tmp path.
os.environ["ARSLAN_SECRET_KEY_FILE"] = ""

import shutil
from pathlib import Path

import pytest

from arslan.models import (
    DomainInfo,
    PersonaSpec,
    RuntimeSpec,
    SpawnRequirements,
    ToolSpec,
)
from tests import real_data_dir_guard

# No test may write into the user's real data dir (tests/real_data_dir_guard.py).
# Pinned here for the same reason as the secret file above: before any server.*
# import builds the settings singleton. The snapshot is taken now too, so writes
# made while test modules are collected are caught as well.
_SUITE_DATA_DIR = real_data_dir_guard.pin_suite_data_dir()
_REAL_DATA_DIR_AT_START = real_data_dir_guard.snapshot()


@pytest.fixture
def sample_domain() -> DomainInfo:
    return DomainInfo(category="content-creator", subcategory="xiaohongshu")


@pytest.fixture
def sample_persona() -> PersonaSpec:
    return PersonaSpec(
        role="资深美妆博主",
        tone="数据实测型",
        constraints=["不推荐未经验证的产品"],
    )


@pytest.fixture
def sample_tool() -> ToolSpec:
    return ToolSpec(
        name="web_search",
        description="Search the web for information",
        tags=["search", "web"],
        input_schema={"query": {"type": "string"}},
        output_schema={"results": {"type": "array"}},
    )


@pytest.fixture
def sample_requirements(sample_domain, sample_persona) -> SpawnRequirements:
    return SpawnRequirements(
        spawn_name="美妆助手",
        domain=sample_domain,
        capabilities=["content-generation", "info-gathering"],
        persona=sample_persona,
        runtime=RuntimeSpec(platform="web", trigger="user"),
        research_results={"trends": ["skincare", "makeup"]},
    )


@pytest.fixture(autouse=True)
def _default_workspace_in_tmp(tmp_path_factory):
    """0.1.48: Arslan's default folder is ~/Arslan; no test may create or write it.

    Its own MonkeyPatch, not the shared `monkeypatch` fixture: requesting that here
    (a root-level autouse fixture) would set it up before tests/server/conftest's
    `_restore_config_after_test` and so tear it down after it — and that teardown
    relies on running after monkeypatch has restored the test's patches."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("ARSLAN_DEFAULT_WORKSPACE", str(tmp_path_factory.mktemp("arslan-home") / "Arslan"))
        yield


@pytest.fixture(autouse=True)
def _no_judge_model_calls():
    """0.1.52: shadow judgments fire at every confirmation card. In tests the judge
    model is never reached (no network, no spend); a test of the judgment layer
    patches `_adapter` itself. Its own MonkeyPatch, for the reason given above."""
    from server.services import judgment

    async def disabled():
        raise RuntimeError("judge model disabled in tests")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(judgment, "_adapter", disabled)
        yield


@pytest.fixture(autouse=True)
def _data_dir_pin_survives():
    """Repair, then fail, a test that changed the pinned data-dir env and kept it.

    Server tests are repaired earlier, before config is healed, by
    tests/server/conftest.py's `_restore_config_after_test`; this covers the rest."""
    yield
    changed = real_data_dir_guard.restore_pin()
    if changed:
        pytest.fail(f"this test changed {changed} in os.environ and did not restore it "
                    "(repaired now); later tests would resolve the real data dir",
                    pytrace=False)


@pytest.fixture(autouse=True)
def _session_global_restored():
    """Repair, then fail, a test that replaced `db_session.AsyncSessionLocal` and kept it.

    Every later test then gets that test's engine. An in-memory one (StaticPool) shares a
    single connection, and fire-and-forget writes cancelled at teardown closed it twice and
    hung pytest for 120 s (2026-10-04, six fixtures). Use monkeypatch.setattr and dispose
    the engine."""
    from server.db import session as db_session
    before = db_session.AsyncSessionLocal
    yield
    if db_session.AsyncSessionLocal is not before:
        db_session.AsyncSessionLocal = before
        pytest.fail("this test replaced db_session.AsyncSessionLocal and did not restore it "
                    "(repaired now); use monkeypatch.setattr and dispose the engine", pytrace=False)


@pytest.fixture(autouse=True)
def _no_real_network_off_loopback(request):
    """No test reaches the network, whatever code path it takes: a mutant or a regression included.

    Hermeticity used to hold only for a CORRECT implementation. A test replaced the resolver and
    the transport with fakes, and code that went around a fake reached this Mac's real system proxy
    (127.0.0.1:7899, which forwards to the internet) and its real, fake-IP DNS: a review mutation
    run sent about 250 real GETs that way. For every test:
      * `socket.getaddrinfo` refuses any NAME but `localhost`. An address literal needs no network
        to "resolve" and is answered, so the code under test judges it itself (net_pin's
        private-address check must be what refuses 169.254.169.254, not a failed lookup).
        "Address literal" means what net_pin treats as one (`_is_ip_literal`) and a resolver can
        read: an address in whatever spelling the OS takes, `127.1`, `2130706433`, `0x7f000001`,
        `0177.0.0.1` or `10.1` as well as the dotted quad and IPv6. The OS is asked to read it with
        AI_NUMERICHOST, which never goes to DNS, so no spelling can turn into a query. Text that
        only starts like an address is refused like any name: `127.0.0.1.nip.io` is a name, and
        `1.2.3.4.5` is a string net_pin also calls a literal but no resolver reads, so there is no
        address to answer with. `None` and `""` (the empty host) are answered as `None` is
        (loopback): that is no I/O, and net_pin's `_is_non_public` has to be what refuses it.
      * `socket.socket.connect` and `connect_ex` refuse an address that is not loopback: the path
        under asyncio, `socket.create_connection`, urllib, http.client and httpcore. Unix sockets
        and loopback stay open: tests serve from this process and from subprocesses. The address is
        judged as written, so a loopback in an odd spelling (`127.1`) is refused here, which is
        conservative: lookups give the canonical form.
      * a request by a real httpx transport (`AsyncHTTPTransport`, `HTTPTransport`) to a host that
        is not loopback, or through a proxy, a loopback one included, is refused.
      * the proxy environment is scrubbed: HTTP_PROXY, HTTPS_PROXY and ALL_PROXY, upper and lower
        case, are removed and NO_PROXY=* is set. With no proxy variable at all (pytest launched
        from an IDE) urllib on macOS falls back to the SYSTEM proxy, and a real client would send
        even its loopback requests to 127.0.0.1:7899.
    Every refusal is recorded (fixture `network_refusals`) with the thread, and the asyncio task if
    there is one, that asked: a straggler thread of an earlier test that blames a later test is
    found by its name. A test that provoked a refusal it did not expect fails at teardown: code that
    swallows the refusal, as `github_eval.fetch_file` did, is a silent leak. A test that refuses on
    purpose carries `network_refusals_expected`; an opt-in live runner is marked `real_network` (by
    path, in `pytest_collection_modifyitems` below), which lifts all of this and nothing else.

    NOT covered: UDP `sendto`; `gethostbyname`, `getnameinfo` and `gethostbyaddr`; a raw loopback
    socket to a port that is not the test's (the system proxy's, for one); and CHILD PROCESSES (git,
    curl, npm, any subprocess), which inherit the scrubbed environment and none of the patches. A
    net under the fakes, not a sandbox.

    Its own `MonkeyPatch.context()`, never the shared `monkeypatch` fixture, for the reasons given
    at `_default_workspace_in_tmp`; and so that a test's own `monkeypatch.undo()` cannot lift it. A
    test's own resolver patch wins while it is active. tests/test_network_guard.py holds it to all
    of this.
    """
    if request.node.get_closest_marker("real_network") is not None:
        yield []
        return

    import asyncio
    import errno
    import ipaddress
    import socket
    import threading

    import httpcore
    import httpx

    refusals: list[str] = []

    def text(host) -> str:
        return host.decode("ascii", "replace") if isinstance(host, bytes) else str(host)

    def where() -> str:
        """Who asked, for the refusal line: the thread, and the asyncio task if one runs on it."""
        try:
            task = asyncio.current_task()
        except RuntimeError:                       # no event loop is running in this thread
            task = None
        who = f"thread {threading.current_thread().name}"
        return f" [{who}, task {task.get_name()}]" if task is not None else f" [{who}]"

    def loopback(host) -> bool:
        host = text(host)
        if host.lower() == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    real_lookup = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def lookup(host, port, family=0, type=0, proto=0, flags=0):
        if host is None or text(host) == "":
            # Nothing to look up. "" is answered as None is (loopback), whatever this OS makes of
            # it: no I/O on any platform, and net_pin's `_is_non_public` must refuse the answer.
            return real_lookup(None, port, family, type, proto, flags)
        if loopback(host):
            return real_lookup(host, port, family, type, proto, flags)
        try:
            # An address in any spelling the OS reads (127.1, 0x7f000001, 2130706433, 10.1) is
            # answered, and AI_NUMERICHOST is what keeps this from ever being a DNS query: the OS
            # reads the text as an address or fails, and a name fails.
            return real_lookup(host, port, family, type, proto, flags | socket.AI_NUMERICHOST)
        except (socket.gaierror, UnicodeError):
            pass
        refusals.append(f"lookup of {text(host)!r}{where()}")
        raise socket.gaierror(socket.EAI_NONAME, f"test guard: a real lookup of {host!r}")

    def leaves_the_machine(sock, address):
        """The host of a connect that is not loopback (None: unix and the like, or loopback)."""
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            return None
        host = address[0] if isinstance(address, tuple) else address
        return None if loopback(host) else host

    def connect(self, address):
        host = leaves_the_machine(self, address)
        if host is not None:
            refusals.append(f"connect to {text(host)!r}{where()}")
            raise OSError(errno.ENETUNREACH, f"test guard: a real connect to {text(host)!r}")
        return real_connect(self, address)

    def connect_ex(self, address):
        host = leaves_the_machine(self, address)
        if host is not None:
            refusals.append(f"connect_ex to {text(host)!r}{where()}")
            return errno.ENETUNREACH
        return real_connect_ex(self, address)

    proxy_pools = tuple(getattr(httpcore, name) for name in
                        ("AsyncHTTPProxy", "HTTPProxy", "AsyncSOCKSProxy", "SOCKSProxy")
                        if hasattr(httpcore, name))

    def check(transport, http_request) -> None:
        host = http_request.url.host
        if not loopback(host):
            refusals.append(f"HTTP transport to {host!r}{where()}")
            raise httpx.ConnectError(f"test guard: a real HTTP transport was asked to reach "
                                     f"{host}", request=http_request)
        if isinstance(getattr(transport, "_pool", None), proxy_pools):
            refusals.append(f"HTTP transport through a proxy{where()}")
            raise httpx.ConnectError("test guard: a real HTTP transport was asked to go through "
                                     "a proxy", request=http_request)

    real_async = httpx.AsyncHTTPTransport.handle_async_request
    real_sync = httpx.HTTPTransport.handle_request

    async def guarded_async(self, http_request):
        check(self, http_request)
        return await real_async(self, http_request)

    def guarded_sync(self, http_request):
        check(self, http_request)
        return real_sync(self, http_request)

    with pytest.MonkeyPatch.context() as mp:
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            mp.delenv(var, raising=False)
        mp.setenv("NO_PROXY", "*")
        mp.setenv("no_proxy", "*")
        mp.setattr(socket, "getaddrinfo", lookup)
        mp.setattr(socket.socket, "connect", connect)
        mp.setattr(socket.socket, "connect_ex", connect_ex)
        mp.setattr(httpx.AsyncHTTPTransport, "handle_async_request", guarded_async)
        mp.setattr(httpx.HTTPTransport, "handle_request", guarded_sync)
        yield refusals
    if refusals and request.node.get_closest_marker("network_refusals_expected") is None:
        pytest.fail(
            "this test tried to reach the network, and the guard (tests/conftest.py, "
            "_no_real_network_off_loopback) refused it, but the test did not expect that:\n  - "
            + "\n  - ".join(refusals)
            + "\nFake what the code reached (a refusal the code swallows is a silent leak), or mark "
            "the test `real_network` (an opt-in live runner) or `network_refusals_expected` "
            "(refusing is the point).", pytrace=False)


@pytest.fixture
def network_refusals(_no_real_network_off_loopback):
    """What the network guard refused during this test, in order (always empty under `real_network`)."""
    return _no_real_network_off_loopback


#: The opt-in live runners: each calls a model API or public pages once its own environment opt-in
#: is set, and skips itself otherwise. They are marked `real_network` HERE, by path, and not in the
#: files: they are historical acceptance evidence, several of them frozen by digest (the
#: `freeze_contract` list in evals/companion/stable_retest.py, stable-0140-acceptance.json), and an
#: edit to one would muddle the audit trail. `real_network` lifts the network guard
#: (`_no_real_network_off_loopback`) and nothing else. tests/test_network_guard.py holds this list
#: to the nine runners it names, and checks with `-m real_network` that pytest sees the marker.
_REAL_NETWORK_RUNNERS = (
    "tests/server/test_escalation_eval.py",
    "tests/server/test_stable_document_live.py",
    "tests/server/test_stable_memory_live.py",
    "tests/server/test_stable_research_live.py",
    "tests/server/test_stable_four_live.py",
    "tests/server/test_stable_release_live.py",
    "tests/server/test_stable_retest_live.py",
    "tests/server/test_stable_two_live.py",
    "tests/server/test_stage2_live.py",
)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    """Mark the live runners `real_network`. First, so the marker is there before `-m` selects."""
    root = Path(__file__).resolve().parents[1]
    runners = {(root / relative).resolve() for relative in _REAL_NETWORK_RUNNERS}
    for item in items:
        if item.path.resolve() in runners:
            item.add_marker(pytest.mark.real_network)


@pytest.fixture(scope="session", autouse=True)
def _real_data_dir_untouched():
    """Fail the run if the user's real data dir gained an entry while it ran.

    Reports and never deletes: what is there is the user's, and a false positive (the
    running app creating a new top-level folder mid-run) must not cost them data."""
    yield
    shutil.rmtree(_SUITE_DATA_DIR, ignore_errors=True)
    leaked = real_data_dir_guard.created(_REAL_DATA_DIR_AT_START, real_data_dir_guard.snapshot())
    if leaked:
        root = real_data_dir_guard.REAL_DATA_DIR
        pytest.fail(
            f"this test run created {len(leaked)} entr{'y' if len(leaked) == 1 else 'ies'} "
            f"in the real Arslan data dir {root}:\n"
            + "\n".join(f"  {root / rel}" for rel in leaked)
            + "\nA test resolved the platform data dir instead of a temp one. Run with "
            "HOME pointed at a temp dir to reproduce safely. Nothing was removed.",
            pytrace=False,
        )
