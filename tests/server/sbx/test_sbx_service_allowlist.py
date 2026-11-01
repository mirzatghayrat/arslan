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
    # dns-any-declared-default-deny; product SSH accepts IPv4 literals only.
    sbx.network = mode
    case = next(case for case in CASES if case.name == "dns")
    control = sbx.run(case.argv, profile="(version 1)(allow default)", probe="dns-control")
    assert control.returncode == 0, control.stderr
    result = sbx.run(case.argv, probe="dns-" + mode.value + "-default-deny")
    granted = mode == NetworkMode.ANY_DECLARED
    assert (result.returncode == 0) == granted, result.stderr
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
    assert int(channel.stdout) == 0 if granted else int(channel.stdout) in (errno.EPERM, errno.EACCES)


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
def test_trust_service_is_limited_to_measured_https_mode(sbx, mode, record_property):
    from tests.server.sbx.corpus.test_sbx2_corpus import test_compatibility_measurement

    sbx.network = mode
    result = sbx.run([sys.executable, "-I", str(PROBE), "mach-lookup", "com.apple.trustd.agent"],
                     probe="trust-service-policy")
    assert result.returncode == 0, result.stderr
    answer = json.loads(result.stdout)
    if mode != NetworkMode.ANY_DECLARED:
        assert answer["policy"] == 1 and answer["lookup"] != 0, answer
        return
    assert answer == {"policy": 0, "lookup": 0}, answer
    # swift-certificate-any-declared-default-deny still fails after DNS alone.
    # Use the corpus row itself, including its redirected caches and time limit.
    case = next(case for case in CASES if case.name == "swift-certificate")
    properties = {}
    test_compatibility_measurement(sbx, case, mode, properties.__setitem__)
    for key, value in properties.items():
        record_property(key, value)
    assert properties["outcome"] == "ok", properties
