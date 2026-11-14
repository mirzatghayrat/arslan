"""Measured service grants, with live resolver/watch controls and mode boundaries."""
import errno
import json
import shutil
import sys
from pathlib import Path

import pytest

from server.services.sandbox_profile import NetworkMode
from tests.server.sbx.corpus.test_sbx2_corpus import CASES

pytestmark = pytest.mark.sbx_mac
macos = pytest.mark.skipif(sys.platform != "darwin", reason="macOS seatbelt")
DNS_SOCKET = "/private/var/run/mDNSResponder"
FSEVENTS = "com.apple.FSEvents"
PROBE = Path(__file__).parent / "corpus" / "service_probe.py"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("mode", list(NetworkMode))
def test_dns_corpus_and_resolver_channel_follow_network_mode(sbx, mode):
    # No mode grants DNS: online is the proxy, and product SSH accepts IPv4 literals only.
    sbx.network = mode
    case = next(case for case in CASES if case.name == "dns")
    # The control needs no answer from the runner's DNS (a 30 s CI hang): mDNSResponder answers `localhost.`
    # itself. Bare `localhost` is answered in-process without the channel, so the trailing dot is load-bearing.
    local = (*case.argv[:-1], case.argv[-1].replace("'example.com'", "'localhost.'"))
    assert local != case.argv
    control = sbx.run(local, profile="(version 1)(allow default)", probe="dns-control", timeout=10)
    assert control.returncode == 0, control.stderr
    # The control's name resolves only through the resolver channel: closing just that socket fails it.
    unreachable = f'(version 1)(allow default)(deny network-outbound (literal "{DNS_SOCKET}"))'
    closed = sbx.run(local, profile=unreachable, probe="dns-control-channel-closed", timeout=10)
    assert closed.returncode != 0, closed.stderr
    # Local name first: a policy that opened the channel fails there without waiting on the network.
    for argv, probe in ((local, "dns-local-"), (case.argv, "dns-")):
        result = sbx.run(argv, probe=probe + mode.value + "-default-deny")
        assert result.returncode != 0, result.stderr
    # A cached name result is not evidence that the resolver channel is closed.
    # Connect only, with no protocol bytes; policy must refuse the socket itself.
    channel = sbx.python("""
import socket, sys
with socket.socket(socket.AF_UNIX) as sock:
    try:
        sock.connect(sys.argv[1])
    except OSError as exc:
        print(exc.errno)
    else:
        print(0)
""", DNS_SOCKET, probe="resolver-channel")
    assert channel.returncode == 0, channel.stderr
    assert int(channel.stdout) in (errno.EPERM, errno.EACCES)


@pytest.mark.macos
@macos
@pytest.mark.parametrize("mode", list(NetworkMode))
def test_fsevents_restores_node_watch(sbx, mode):
    # node-watch-none-default-deny; watching scratch files needs no network.
    sbx.network = mode
    argv = [sys.executable, "-I", str(PROBE), "mach-lookup", FSEVENTS]
    lookup = sbx.run(argv, probe="fsevents-lookup")
    assert lookup.returncode == 0, lookup.stderr
    assert json.loads(lookup.stdout) == {"policy": 0, "lookup": 0}
    case = next(case for case in CASES if case.name == "node-watch")
    result = sbx.run(case.argv, probe="node-watch-" + mode.value + "-default-deny")
    assert result.returncode == 0, result.stderr
    shutil.rmtree(sbx.work / "watch")
    # Removing just this entry must restore the original failed corpus row.
    without = sbx.profile().replace('(allow mach-lookup (global-name "com.apple.FSEvents"))\n', '')
    assert without != sbx.profile()
    lookup = sbx.run(argv, profile=without, probe="fsevents-withheld")
    assert lookup.returncode == 0 and json.loads(lookup.stdout)["policy"] == 1
    result = sbx.run(case.argv, profile=without, probe="node-watch-withheld")
    assert result.returncode != 0


@pytest.mark.macos
@macos
@pytest.mark.parametrize("mode", list(NetworkMode))
def test_trust_service_is_limited_to_measured_https_mode(sbx, mode):
    # The base grants the trust service in no mode; only the user's setting adds it, in proxy mode
    # (test_sbx6_settings.py).
    sbx.network = mode
    result = sbx.run([sys.executable, "-I", str(PROBE), "mach-lookup", "com.apple.trustd.agent"],
                     probe="trust-service-policy")
    assert result.returncode == 0, result.stderr
    answer = json.loads(result.stdout)
    assert answer["policy"] == 1 and answer["lookup"] != 0, answer


@pytest.mark.macos
@macos
@pytest.mark.parametrize("mode", list(NetworkMode))
def test_raw_udp_is_refused_in_every_mode(sbx, mode):
    import socket

    sbx.network = mode
    source = """
import socket, sys
with socket.socket(int(sys.argv[1]), socket.SOCK_DGRAM) as client:
    try:
        client.sendto(b'sbx', (sys.argv[2], int(sys.argv[3])))
    except OSError as exc:
        print(exc.errno)
    else:
        print(0)
"""
    # Test-owned loopback endpoints; no DNS, LAN traffic or daemon RPCs.
    for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        with socket.socket(family, socket.SOCK_DGRAM) as receiver:
            receiver.bind((address, 0))
            receiver.settimeout(3)
            port = receiver.getsockname()[1]
            control = sbx.python(source, family, address, port,
                                 profile="(version 1)(allow default)", probe="udp-control-" + family.name)
            assert control.returncode == 0 and control.stdout.strip() == "0", control.stderr
            assert receiver.recv(16) == b"sbx"
            denied = sbx.python(source, family, address, port, probe="udp-refusal-" + family.name)
            assert denied.returncode == 0, denied.stderr
            assert int(denied.stdout) in (errno.EPERM, errno.EACCES)
