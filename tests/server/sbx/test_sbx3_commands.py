"""Commands denial contract. SBX-3a registers the product adapter, never a fallback.

Only the off-platform skip applies on Linux. On macOS the absent adapter is a
strict expected assertion; registered adapters must run every gate without it.
"""
import errno
import json
import os
from pathlib import Path
import socket
import sys
import tempfile

import pytest

from server.services.sandbox_profile import NetworkMode
from tests.server.sbx import test_sbx2_kernel as gates
from tests.server.sbx.harness import BUILT_BASES, Harness

pytestmark = [pytest.mark.sbx_mac, pytest.mark.parametrize("sbx", [
    pytest.param("commands", marks=pytest.mark.xfail(
        "commands" not in BUILT_BASES, strict=True, raises=AssertionError,
        reason="SBX-3a commands adapter is not built")),
], indirect=True)]
macos = pytest.mark.skipif(sys.platform != "darwin", reason="macOS seatbelt")
APP_DATA = (
    "Library/Mail", "Library/Containers/com.apple.mail", "Library/Messages",
    "Library/Containers/com.apple.MobileSMS", "Library/Safari", "Library/Photos",
    "Library/Containers/com.apple.Photos", "Pictures/Photos Library.photoslibrary",
)


@pytest.mark.macos
@macos
@pytest.mark.parametrize("mode", [NetworkMode.NONE, NetworkMode.PROXY])
@pytest.mark.parametrize("service", gates.SERVICES.values(), ids=gates.SERVICES.keys())
def test_commands_services(sbx, mode, service, record_property):
    gates.test_service_policy_and_reachability(sbx, mode, service, record_property)


@pytest.mark.macos
@macos
def test_commands_preference_writes(sbx):
    gates.test_preference_policy_distinguishes_reads_from_writes(sbx)


@pytest.mark.macos
@macos
def test_commands_launch_submission(sbx):
    # Seatbelt can reject submission even under allow-default. Also require the
    # profile's explicit service boundary, so that ambient refusal cannot pass.
    check = sbx.run([sys.executable, "-I", gates.PROBE, "mach-lookup", gates.SERVICES["launchd"]],
                    probe="commands-launch-policy")
    assert check.returncode == 0, check.stderr
    assert json.loads(check.stdout)["policy"] == 1
    gates.test_launch_submission_is_refused(sbx)


@pytest.mark.macos
@macos
def test_commands_unlisted_unix_socket(sbx):
    gates.test_unlisted_unix_socket_is_refused_in_every_network_mode(sbx)


@pytest.mark.macos
@macos
def test_commands_filesystem_boundaries(sbx):
    gates.test_read_write_and_protected_paths(sbx)


@pytest.mark.macos
@macos
def test_commands_signal_boundary_and_pty(sbx):
    gates.test_same_sandbox_signals_and_pty(sbx)


@pytest.mark.macos
@macos
def test_commands_ipc_namespace(sbx):
    # This tests confinement, not the Pool compatibility row that SBX-M failed.
    gates.test_posix_ipc_is_confined_to_the_run_prefix(sbx)


@pytest.mark.macos
@macos
def test_commands_apple_events(sbx):
    gates.test_apple_events_refused_without_contacting_an_app(sbx)


@pytest.mark.macos
@macos
@pytest.mark.parametrize("mode", [NetworkMode.PROXY])
def test_commands_listener_and_arslan_port(sbx, mode):
    gates.test_listener_refusal_and_arslan_port_exclusion(sbx, mode)


@pytest.mark.macos
@macos
def test_commands_devices(sbx):
    gates.test_device_writes_are_narrow(sbx)


@pytest.mark.macos
@macos
def test_commands_offline_closes_loopback(sbx):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        source = """
import socket, sys
with socket.socket() as sock:
    try:
        sock.connect(('127.0.0.1', int(sys.argv[1])))
    except OSError as exc:
        print(exc.errno)
    else:
        print(0)
"""
        port = listener.getsockname()[1]
        control = sbx.python(source, port, profile="(version 1)(allow default)",
                             probe="commands-offline-control")
        assert control.returncode == 0 and control.stdout.strip() == "0", control.stderr
        denied = sbx.python(source, port, probe="commands-offline-loopback")
        assert denied.returncode == 0, denied.stderr
        assert int(denied.stdout) in (errno.EPERM, errno.EACCES), denied.stdout


@pytest.mark.macos
@macos
@pytest.mark.parametrize("relative", APP_DATA)
def test_commands_closed_app_data(sbx, relative):
    folder = sbx.home / relative
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "sbx-sentinel"
    target.write_text("original")
    alias = sbx.work / "app-data-alias"
    alias.symlink_to(folder, target_is_directory=True)
    source = """
import errno, pathlib, sys
for name in sys.argv[1:]:
    path = pathlib.Path(name)
    for action in ('read', 'write'):
        try:
            path.read_text() if action == 'read' else path.write_text('changed')
        except OSError as exc:
            assert exc.errno in (errno.EPERM, errno.EACCES), exc
        else:
            raise AssertionError('app data boundary allowed: ' + action)
print('checked')
"""
    # Host-owned scratch data avoids TCC or file absence masquerading as denial.
    assert target.read_text() == (alias / target.name).read_text() == "original"
    result = sbx.python(source, target, alias / target.name, probe="commands-app-data")
    assert result.returncode == 0 and result.stdout.strip() == "checked", result.stderr
    assert target.read_text() == "original"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("location", ["tmp", "var-tmp", "darwin-T", "darwin-C", "darwin-parent", "other-run"])
def test_commands_private_temp_boundary(sbx, location):
    darwin_temp = Path(os.confstr(65537)).resolve()
    other = Harness(sbx.root / "second-run", sbx.base, executions=sbx.executions)
    assert other.temp != sbx.temp
    parents = {"tmp": Path("/private/tmp"), "var-tmp": Path("/private/var/tmp"),
               "darwin-T": darwin_temp, "darwin-C": darwin_temp.parent / "C",
               "darwin-parent": darwin_temp.parent, "other-run": other.temp}
    with tempfile.TemporaryDirectory(prefix="sbx3-other-", dir=parents[location]) as folder:
        target = Path(folder) / "sentinel"
        target.write_text("original")
        assert not target.is_relative_to(sbx.work) and not target.is_relative_to(sbx.temp)
        result = sbx.python("""
import errno, os, pathlib, sys
private = pathlib.Path(os.environ['TMPDIR'])
(private / 'own').write_text('ok')
try:
    pathlib.Path(sys.argv[1]).write_text('changed')
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES), exc
else:
    raise AssertionError('shared or another run temp writable')
print('checked')
""", target, probe="commands-temp-" + location)
        assert result.returncode == 0 and result.stdout.strip() == "checked", result.stderr
        assert target.read_text() == "original"
        assert (sbx.temp / "own").read_text() == "ok"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("protected", [False, True], ids=["outside-roots", "protected"])
def test_commands_hardlink_boundary(sbx, protected):
    target = (sbx.protected if protected else sbx.root) / "hardlink-sentinel"
    target.write_text("original")
    assert target.stat().st_dev == sbx.work.stat().st_dev, "hard-link control requires one volume"
    result = sbx.python("""
import errno, os, pathlib, sys
# A blanket link ban must fail: ordinary links inside the workspace still work.
pathlib.Path('local-source').write_text('local')
os.link('local-source', 'local-alias')
assert pathlib.Path('local-alias').read_text() == 'local'
target = pathlib.Path(sys.argv[1])
try:
    target.write_text('direct')
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES), exc
else:
    raise AssertionError('target is directly writable; not a boundary')
try:
    os.link(target, 'outside-alias')
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES), exc
else:
    # The optional protected-set contract requires link creation itself refused.
    assert sys.argv[2] == 'False', 'protected file link allowed'
    try:
        pathlib.Path('outside-alias').write_text('changed')
    except OSError as exc:
        assert exc.errno in (errno.EPERM, errno.EACCES), exc
    else:
        raise AssertionError('hard-link write allowed')
print('checked')
""", target, protected, probe="commands-hardlink")
    assert result.returncode == 0 and result.stdout.strip() == "checked", result.stderr
    assert target.read_text() == "original"
