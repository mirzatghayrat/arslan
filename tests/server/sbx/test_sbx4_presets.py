"""SBX-4a registers product adapters; these gates never substitute a candidate."""
import errno
import json
import re
import socket
import sys

import pytest

from server.services.sandbox_profile import NetworkMode
from tests.server.sbx import test_sbx2_kernel as gates
from tests.server.sbx import test_sbx_service_allowlist as services
from tests.server.sbx.harness import BUILT_BASES, Harness

macos = pytest.mark.skipif(sys.platform != "darwin", reason="macOS seatbelt")
SURFACES = (("run-python", NetworkMode.NONE), ("artifact", NetworkMode.NONE),
            ("mcp", NetworkMode.NONE), ("mcp", NetworkMode.ANY_DECLARED))


def pending(base):
    stage = "SBX-3a" if base == "commands" else "SBX-4a"
    message = f"{stage} {base} adapter is not built"
    return pytest.mark.xfail(base not in BUILT_BASES, strict=True,
                            raises=pytest.RaisesExc(AssertionError, match="^" + message),
                            reason=message)


cases = pytest.mark.parametrize("sbx,mode", [
    pytest.param(base, mode, marks=pending(base), id=base + "-" + mode.value)
    for base, mode in SURFACES], indirect=["sbx"])


@pytest.mark.parametrize("base", [pytest.param(base, marks=pending(base)) for base in
                                  ("commands", "run-python", "artifact", "mcp")]
                              + ["outside-floor", "ssh", "default-deny"])
def test_presets_have_no_wholesale_grants(tmp_path, base):
    if base == "ssh":
        from server.services.ssh_exec import ssh_profile
        text = ssh_profile()
    else:
        stage = "SBX-3a" if base == "commands" else "SBX-4a"
        assert base in BUILT_BASES, f"{stage} {base} adapter is not built"
        text = Harness(tmp_path, base).profile()
    # Ignore quoted paths, but include modifier-first and wildcard operations.
    for line in text.splitlines():
        code = re.sub(r'"(?:\\.|[^"\\])*"', '""', line)
        if not re.match(r"\s*\(allow\b", code):
            continue
        assert not re.search(r"\buser-preference-write\b", code), line
        assert not re.search(r"\bmach\*(?:\s|\))", code), line
        if re.search(r"\bmach-lookup\b", code):
            assert "(global-name " in line and "global-name-prefix" not in line, line
        if base not in {"outside-floor", "ssh"}:
            assert not re.search(r"\bdefault\b", code), line


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@cases
@pytest.mark.parametrize("service", gates.SERVICES.values(), ids=gates.SERVICES.keys())
def test_preset_services(sbx, mode, service, record_property):
    gates.test_service_policy_and_reachability(sbx, mode, service, record_property)


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@cases
def test_preset_network(sbx, mode):
    services.test_raw_udp_is_refused_in_every_mode(sbx, mode)
    source = """
import socket, sys
with socket.socket(int(sys.argv[1])) as client:
    try:
        client.connect(sys.argv[2] if int(sys.argv[1]) == socket.AF_UNIX else (sys.argv[2], int(sys.argv[3])))
    except OSError as exc:
        print(exc.errno)
    else:
        print(0)
"""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        for family, host, port in ((socket.AF_INET, "127.0.0.1", listener.getsockname()[1]),
                                   (socket.AF_UNIX, services.DNS_SOCKET, 0)):
            control = sbx.python(source, family, host, port, profile="(version 1)(allow default)",
                                 probe="preset-network-control")
            assert control.returncode == 0 and control.stdout.strip() == "0", control.stderr
            result = sbx.python(source, family, host, port, probe="preset-network")
            assert result.returncode == 0, result.stderr
            if mode == NetworkMode.NONE:
                assert int(result.stdout) in (errno.EPERM, errno.EACCES), result.stdout
            else:
                assert result.stdout.strip() == "0", result.stdout


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@cases
def test_preset_unlisted_socket(sbx, mode):
    # Reuse the shared real listener gate, but keep the surface's declared mode.
    gates.test_unlisted_unix_socket_is_refused_in_every_network_mode(sbx, modes=(mode,))


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@cases
def test_preset_preference_and_unlisted_service_policy(sbx, mode):
    for operation, name in (("user-preference-write", "com.arslan.sbx-probe.no-write"),
                            ("mach-lookup", "com.arslan.sbx-probe.unlisted")):
        result = sbx.python(gates.PROBE.read_text(), operation, name, probe="preset-" + operation)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["policy"] == 1, result.stdout


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@cases
def test_preset_filesystem(sbx, mode):
    grant = sbx.root / "grant"
    grant.mkdir(exist_ok=True)
    protected = grant / "protected"
    protected.mkdir(exist_ok=True)
    reference = sbx.work / "references"
    reference.mkdir(exist_ok=True)
    targets = [sbx.root / "outside", protected / "sentinel"]
    (reference / "input").write_text("original")
    if sbx.base == "run-python":
        targets.append(reference / "input")
    for target in targets:
        target.write_text("original")
    options = dict(granted_folders=[grant], protected=[protected], references=reference)
    profile = sbx.profile(**options)
    source = """
import errno, pathlib, sys
pathlib.Path('own').write_text('ok')
if sys.argv[1] == 'mcp':
    (pathlib.Path(sys.argv[2]) / 'own').write_text('ok')
for name in sys.argv[3:]:
    target = pathlib.Path(name)
    try:
        target.write_text('changed')
    except OSError as exc:
        assert exc.errno in (errno.EPERM, errno.EACCES), exc
    else:
        raise AssertionError('preset write boundary opened')
print('checked')
"""
    result = sbx.python(source, sbx.base, grant, *targets, profile=profile, probe="preset-writes")
    assert result.returncode == 0 and result.stdout.strip() == "checked", result.stderr
    assert all(target.read_text() == "original" for target in targets)
    # Computation reads are as narrow as today's policy, not commands' broad reads.
    if sbx.base != "mcp":
        result = sbx.python("""
import errno, pathlib, sys
assert pathlib.Path(sys.argv[2]).read_text() == 'original'
try:
    pathlib.Path(sys.argv[1]).read_text()
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES), exc
else:
    raise AssertionError('computation host read allowed')
print('checked')
""", targets[0], reference / "input", profile=profile, probe="computation-reads")
        assert result.returncode == 0 and result.stdout.strip() == "checked", result.stderr
