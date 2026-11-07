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
    stage = "SBX-3a" if base == "commands" else "SBX-6a" if base == "mcp-proxy" else "SBX-4a"
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
        stage = "SBX-3a" if base == "commands" else "SBX-6a" if base == "mcp-proxy" else "SBX-4a"
        assert base in BUILT_BASES, f"{stage} {base} adapter is not built"
        text = Harness(tmp_path, base).profile()
    # Read complete top-level forms, including multiline/modifier-first grants.
    # Lex comments and strings together: a quote inside a comment must never
    # consume a later rule. Comment delimiters inside strings are data too.
    parts = []
    i = 0
    while i < len(text):
        if text[i] == ";":
            end = text.find("\n", i)
            i = len(text) if end == -1 else end
            parts.append(" ")
        elif text.startswith("#|", i):
            block_depth = 1
            i += 2
            while block_depth:
                assert i < len(text), "unclosed policy block comment"
                if text.startswith("#|", i):
                    block_depth += 1
                    i += 2
                elif text.startswith("|#", i):
                    block_depth -= 1
                    i += 2
                else:
                    i += 1
            parts.append(" ")
        elif text[i] == '"':
            i += 1
            while i < len(text) and text[i] != '"':
                # sbpl_string escapes quotes/backslashes and writes controls as
                # \xHH. Skip the escaped character; hex digits remain data.
                i += 2 if text[i] == "\\" else 1
            assert i < len(text), "unclosed policy string"
            i += 1
            parts.append('""')
        else:
            parts.append(text[i])
            i += 1
    code = "".join(parts)
    forms = []
    depth = 0
    for token in re.finditer(r"[()]", code):
        if token.group() == "(":
            if depth == 0:
                start = token.start()
            depth += 1
        else:
            depth -= 1
            assert depth >= 0, "unbalanced policy form"
            if depth == 0:
                forms.append(code[start:token.end()])
    assert depth == 0, "unclosed policy form"
    for form in forms:
        form = re.sub(r"\s+", " ", form)
        form = re.sub(r"\(\s+", "(", form)
        if not re.match(r"\(allow\b", form):
            continue
        assert not re.search(r"\buser-preference-write\b", form), form
        assert not re.search(r"\bmach\*(?:\s|\))", form), form
        if re.search(r"\bmach-lookup\b", form):
            assert "(global-name " in form and "global-name-prefix" not in form, form
        if base not in {"outside-floor", "ssh"}:
            assert not re.search(r"\bdefault\b", form), form



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
            if mode == NetworkMode.NONE or (mode == NetworkMode.PROXY and family == socket.AF_UNIX):
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
def test_preset_apple_events(sbx, mode):
    control = sbx.run(["/usr/bin/osascript", "-e", "return 1"],
                      profile="(version 1)(allow default)", probe="osascript-executable-control")
    assert control.returncode == 0 and control.stdout.strip() == "1", control.stderr
    control = sbx.python("""
import ctypes as C, os
lib = C.CDLL('/usr/lib/libsandbox.dylib')
lib.sandbox_check.argtypes = [C.c_int, C.c_char_p, C.c_int]
flag = C.c_int.in_dll(lib, 'SANDBOX_CHECK_NO_REPORT').value
assert lib.sandbox_check(os.getpid(), b'appleevent-send', flag) == 0
""", profile="(version 1)(allow default)", probe="apple-event-policy-control")
    assert control.returncode == 0, control.stderr
    # No live app receives an event. The policy query distinguishes a denied
    # operation from the intentionally absent target of the execution probe.
    gates.test_apple_events_refused_without_contacting_an_app(sbx)


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@cases
def test_preset_launch_submission(sbx, mode):
    # As for commands, launchd may refuse even allow-default. Pin the missing
    # lookup grant too: ambient rejection alone must not satisfy this gate.
    for profile, expected in (("(version 1)(allow default)", 0), (sbx.profile(), 1)):
        result = sbx.python(gates.PROBE.read_text(), "mach-lookup",
                            "com.arslan.sbx-probe.launch-policy", profile=profile,
                            probe="preset-launch-policy")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["policy"] == expected, result.stdout
    # The shared gate controls the executable and live user domain, submits a
    # unique inert job, checks its absence, and cleans that label in all paths.
    gates.test_launch_submission_is_refused(sbx)


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
if sys.argv[1] in {'mcp', 'mcp-proxy'}:
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
    if sbx.base not in {"mcp", "mcp-proxy"}:
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
    else:
        result = sbx.python("""
import errno, pathlib, sys
assert pathlib.Path(sys.argv[1]).read_text() == 'ok'
try:
    pathlib.Path(sys.argv[2]).read_text()
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES), exc
else:
    raise AssertionError('MCP protected read allowed inside a granted folder')
print('checked')
""", grant / "own", protected / "sentinel", profile=profile, probe="mcp-protected-read")
        assert result.returncode == 0 and result.stdout.strip() == "checked", result.stderr
