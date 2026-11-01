"""SBX-6 network gates. Loopback dev servers are the user's explicit exception."""
from contextlib import ExitStack
import errno
import re
import socket
import sys

import pytest

from server.services.sandbox_profile import NetworkMode
from tests.server.sbx import test_sbx2_kernel as gates
from tests.server.sbx import test_sbx_service_allowlist as services
from tests.server.sbx.harness import BUILT_BASES, Harness

macos = pytest.mark.skipif(sys.platform != "darwin", reason="macOS seatbelt")
PROXY_BASES = ("commands-proxy", "mcp-proxy")


def pending(base):
    message = f"SBX-6a {base} adapter is not built"
    return pytest.mark.xfail(base not in BUILT_BASES, strict=True,
                            raises=pytest.RaisesExc(AssertionError, match="^" + message), reason=message)


def bases(names):
    return pytest.mark.parametrize("net_sbx", [pytest.param(b, marks=pending(b)) for b in names], indirect=True)


@pytest.fixture
def net_sbx(tmp_path, request, record_property):
    base = request.param
    assert base in BUILT_BASES, f"SBX-6a {base} adapter is not built"
    h = Harness(tmp_path, base, NetworkMode.PROXY)
    with socket.socket() as proxy:
        proxy.bind(("127.0.0.1", 0))
        proxy.listen(4)
        h.proxy_port = proxy.getsockname()[1]
        try:
            yield h
        finally:
            h.record_executions(record_property, request.config.getoption("--sbx-artifacts"))


@pytest.fixture
def listeners():
    with ExitStack() as stack:
        sockets = {}
        for role, family, host in (("proxy", socket.AF_INET, "127.0.0.1"),
                                    ("dev", socket.AF_INET, "127.0.0.1"),
                                    ("api", socket.AF_INET, "127.0.0.1"),
                                    ("browser-connect", socket.AF_INET, "127.0.0.1"),
                                    ("extra-startup", socket.AF_INET, "127.0.0.1"),
                                    ("system", socket.AF_INET, "127.0.0.1"),
                                    ("system-v6", socket.AF_INET6, "::1")):
            listener = stack.enter_context(socket.socket(family))
            if family == socket.AF_INET6:
                listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            listener.bind((host, 0))
            listener.listen(64)
            sockets[role] = listener
        yield {role: s.getsockname()[1] for role, s in sockets.items()}


def options(ports):
    # Stand-ins for the actual bind registry: never a hard-coded API/tunnel port.
    return {"proxy_port": ports["proxy"],
            "bound_ports": [ports[name] for name in ("api", "browser-connect", "extra-startup")],
            "system_proxies": []}


def connect(h, host, port, *, profile, allowed, probe):
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    source = """
import socket, sys
with socket.socket(int(sys.argv[1])) as client:
    client.settimeout(3)
    try:
        client.connect((sys.argv[2], int(sys.argv[3])))
    except OSError as exc:
        print(exc.errno)
    else:
        print(0)
"""
    control = h.python(source, family, host, port, profile="(version 1)(allow default)", probe=probe + "-control")
    assert control.returncode == 0 and control.stdout.strip() == "0", control.stderr
    result = h.python(source, family, host, port, profile=profile, probe=probe)
    assert result.returncode == 0, result.stderr
    assert int(result.stdout) == 0 if allowed else int(result.stdout) in (errno.EPERM, errno.EACCES), result.stdout


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@bases(PROXY_BASES)
def test_proxy_and_dev_work_but_direct_and_arslan_ports_do_not(net_sbx, listeners):
    text = net_sbx.profile(**options(listeners))
    connect(net_sbx, "127.0.0.1", listeners["proxy"], profile=text, allowed=True, probe="proxy")
    # Queue item 8 / §3 loopback qualifies item 1: dev-server loopback stays open.
    connect(net_sbx, "127.0.0.1", listeners["dev"], profile=text, allowed=True, probe="dev")
    for role in ("api", "browser-connect", "extra-startup"):
        for host in ("127.0.0.1", "::ffff:127.0.0.1"):
            connect(net_sbx, host, listeners[role], profile=text, allowed=False, probe=role + "-refusal")
    # A connection to this Mac's own NIC address is still local to the kernel,
    # not an off-host control. Nonblocking TEST-NET connect distinguishes an
    # immediate policy denial from an admitted attempt without needing an
    # Internet server to answer. No application bytes or DNS request are sent.
    source = """
import socket, sys
with socket.socket() as client:
    client.setblocking(False)
    print(client.connect_ex(('192.0.2.1', int(sys.argv[1]))))
"""
    control = net_sbx.python(source, listeners["dev"], profile="(version 1)(allow default)", probe="off-host-control")
    assert control.returncode == 0, control.stderr
    assert int(control.stdout) in (0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY), control.stdout
    refused = net_sbx.python(source, listeners["dev"], profile=text, probe="off-host-refusal")
    assert refused.returncode == 0, refused.stderr
    assert int(refused.stdout) in (errno.EPERM, errno.EACCES), refused.stdout



@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@bases((*PROXY_BASES, "run-python", "network-sbx6"))
def test_resolver_and_raw_udp_are_refused(net_sbx, listeners):
    mode = (NetworkMode.NONE if net_sbx.base == "run-python" else
            NetworkMode.PORT_22 if net_sbx.base == "network-sbx6" else NetworkMode.PROXY)
    net_sbx.network = mode
    text = net_sbx.profile() if net_sbx.base == "run-python" else net_sbx.profile(**options(listeners))
    source = """
import socket, sys
with socket.socket(socket.AF_UNIX) as client:
    try:
        client.connect(sys.argv[1])
    except OSError as exc:
        print(exc.errno)
    else:
        print(0)
"""
    for profile, expected in (("(version 1)(allow default)", {0}), (text, {errno.EPERM, errno.EACCES})):
        result = net_sbx.python(source, services.DNS_SOCKET, profile=profile, probe="resolver-connect-only")
        assert result.returncode == 0, result.stderr
        assert int(result.stdout) in expected, result.stdout
    # Reuse the shared IPv4/IPv6 UDP gate with this exact executed profile.
    from unittest.mock import patch
    with patch.object(net_sbx, "profile", return_value=text):
        services.test_raw_udp_is_refused_in_every_mode(net_sbx, mode)


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@bases((*PROXY_BASES, "run-python"))
def test_offline_closes_proxy_and_dev_loopback(net_sbx, listeners):
    net_sbx.network = NetworkMode.NONE
    text = net_sbx.profile() if net_sbx.base == "run-python" else net_sbx.profile(**options(listeners))
    for role in ("proxy", "dev"):
        connect(net_sbx, "127.0.0.1", listeners[role], profile=text, allowed=False, probe="offline-" + role)


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("net_sbx,mode", [
    pytest.param(base, mode, marks=pending(base)) for base, mode in (
        ("commands-proxy", NetworkMode.PROXY), ("mcp-proxy", NetworkMode.PROXY),
        ("network-sbx6", NetworkMode.PROXY), ("network-sbx6", NetworkMode.PORT_22))], indirect=["net_sbx"])
@pytest.mark.parametrize("scheme,host", [("http", "localhost"), ("https", "127.0.0.1"), ("socks5", "::1")])
def test_system_proxy_ports_are_closed_but_other_loopback_survives(net_sbx, listeners, mode, scheme, host):
    net_sbx.network = mode
    settings = options(listeners)
    role = "system-v6" if host == "::1" else "system"
    authority = "[::1]" if host == "::1" else host
    settings["system_proxies"] = [f"{scheme}://{authority}:{listeners[role]}"]
    text = net_sbx.profile(**settings)
    # Same host in another spelling must not close Arslan's distinct proxy port.
    connect(net_sbx, "127.0.0.1", listeners["proxy"], profile=text, allowed=True, probe="own-proxy")
    connect(net_sbx, "127.0.0.1", listeners["dev"], profile=text, allowed=True, probe="unrelated-dev")
    for address in (("::1",) if host == "::1" else ("127.0.0.1", "::ffff:127.0.0.1")):
        connect(net_sbx, address, listeners[role], profile=text, allowed=False, probe="system-proxy")


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@bases(("network-sbx6",))
@pytest.mark.parametrize("mode", list(NetworkMode))
@pytest.mark.parametrize("service", gates.SERVICES.values(), ids=gates.SERVICES.keys())
def test_denied_daemons_in_every_network_mode(net_sbx, mode, service, record_property):
    gates.test_service_policy_and_reachability(net_sbx, mode, service, record_property)


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
def test_existing_ssh_still_denies_other_ports_and_resolver(tmp_path, listeners, record_property):
    from server.services import ssh_exec
    h = Harness(tmp_path, "ssh", NetworkMode.PORT_22)
    text = ssh_exec.ssh_profile()
    try:
        connect(h, "127.0.0.1", listeners["dev"], profile=text, allowed=False, probe="ssh-non22")
        result = h.python("""
import errno, socket, sys
with socket.socket(socket.AF_UNIX) as client:
    try:
        client.connect(sys.argv[1])
    except OSError as exc:
        assert exc.errno in (errno.EPERM, errno.EACCES), exc
    else:
        raise AssertionError('SSH resolver channel open')
print('checked')
""", services.DNS_SOCKET, profile=text, probe="ssh-resolver")
        assert result.returncode == 0 and result.stdout.strip() == "checked", result.stderr
        # Keep the existing kernel port-22 positive/negative measurement too.
        from tests.server.test_ssh_exec import test_the_profile_confines_the_port_and_denies_dns
        test_the_profile_confines_the_port_and_denies_dns()
    finally:
        h.record_executions(record_property)


@pytest.mark.parametrize("base", [pytest.param(b, marks=pending(b)) for b in (*PROXY_BASES, "run-python", "network-sbx6")])
def test_complete_network_allow_list(tmp_path, base):
    assert base in BUILT_BASES, f"SBX-6a {base} adapter is not built"
    mode = NetworkMode.NONE if base == "run-python" else NetworkMode.PORT_22 if base == "network-sbx6" else NetworkMode.PROXY
    h = Harness(tmp_path, base, mode)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        text = h.profile() if base == "run-python" else h.profile(proxy_port=port, bound_ports=[], system_proxies=[])
    grants = [line.strip() for line in text.splitlines() if re.match(
        r"\s*\(allow\b.*\b(?:network|default)\b", re.sub(r'"(?:\\.|[^"\\])*"', '""', line))]
    expected = [] if mode == NetworkMode.NONE else [
        '(allow network-outbound (remote tcp "localhost:*"))',
        f'(allow network-outbound (remote tcp "localhost:{port}"))' if mode == NetworkMode.PROXY else
        '(allow network-outbound (remote tcp "*:22"))']
    assert grants == expected, "complete network allow list changed"


@pytest.mark.xfail("commands-proxy" not in BUILT_BASES, strict=True,
                   raises=pytest.RaisesExc(AssertionError, match=r"^SBX-6a commands-proxy adapter is not built"),
                   reason="SBX-6a commands-proxy adapter is not built")
def test_commands_retires_any_declared(tmp_path):
    assert "commands-proxy" in BUILT_BASES, "SBX-6a commands-proxy adapter is not built"
    h = Harness(tmp_path, "commands-proxy", NetworkMode.ANY_DECLARED)
    with pytest.raises(ValueError, match="any-declared"):
        h.profile()
