"""Real Seatbelt gates. Missing services or a broken interpreter are not denial evidence."""
import errno
import json
import os
import plistlib
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from server.services.sandbox_profile import NetworkMode
from tests.server.sbx.harness import DENY_BASES, Harness, base_parameter

pytestmark = [pytest.mark.sbx_mac,
              pytest.mark.parametrize("sbx", [base_parameter(n) for n in DENY_BASES], indirect=True)]

macos = pytest.mark.skipif(sys.platform != "darwin", reason="macOS seatbelt")
PROBE = Path(__file__).parent / "corpus" / "service_probe.py"
SERVICES = {
    "launchd": "com.apple.xpc.launchd",
    "launchservices": "com.apple.coreservices.launchservicesd",
    "launchservices-map": "com.apple.lsd.mapdb",
    "shortcuts": "com.apple.WorkflowKit.ShortcutsViewService",
    "shortcuts-events": "com.apple.siriactionsd",
    "pasteboard": "com.apple.pasteboard.1",
    "windowserver": "com.apple.windowserver.active",
    "tcc": "com.apple.tccd",
    "tcc-system": "com.apple.tccd.system",
    "keychain": "com.apple.securityd",
    "keychain-agent": "com.apple.security.agent",
    "notifications": "com.apple.usernotifications.usernotificationservice",
    "notifications-agent": "com.apple.notificationcenterui.agent",
    "background-network": "com.apple.nsurlsessiond",
    "background-network-system": "com.apple.nsurlsessiond.system",
}


@pytest.mark.macos
@macos
@pytest.mark.parametrize("mode", list(NetworkMode))
@pytest.mark.parametrize("service", SERVICES.values(), ids=SERVICES.keys())
def test_service_policy_and_reachability(sbx, mode, service, record_property):
    sbx.network = mode
    argv = [sys.executable, "-I", str(PROBE), "mach-lookup", service]
    # This control queries reachability only: no RPC, no credential or UI access.
    for base in ("legacy-commands", "outside-floor"):
        control = Harness(sbx.root, base, mode).run(argv)
        assert control.returncode == 0, control.stderr
        observed = json.loads(control.stdout)
        assert observed["policy"] == 0
        record_property(base + "-lookup", observed["lookup"])
    result = sbx.run(argv)
    assert result.returncode == 0, result.stderr
    answer = json.loads(result.stdout)
    assert answer["policy"] == 1, answer  # 1102 (absent service) alone cannot pass.
    assert answer["lookup"] != 0, answer


@pytest.mark.macos
@macos
def test_preference_policy_distinguishes_reads_from_writes(sbx):
    domain = "com.arslan.sbx-probe." + uuid.uuid4().hex
    for operation, expected in (("user-preference-read", 0), ("user-preference-write", 1)):
        result = sbx.run([sys.executable, "-I", str(PROBE), operation, domain])
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["policy"] == expected
    # Only the candidate attempts a write; the baseline never does. Delete the
    # unique domain immediately if the restriction regresses and it is accepted.
    try:
        result = sbx.run(["/usr/bin/defaults", "write", domain, "probe", "-string", "sbx"], discard=True)
        assert result.returncode != 0
        read = subprocess.run(["/usr/bin/defaults", "read", domain, "probe"], env=sbx.env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        assert read.returncode != 0
    finally:
        subprocess.run(["/usr/bin/defaults", "delete", domain], env=sbx.env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


@pytest.mark.macos
@macos
def test_launch_submission_is_refused(sbx):
    label = "com.arslan.sbx-probe." + uuid.uuid4().hex
    job = sbx.work / "probe.plist"
    job.write_bytes(plistlib.dumps({"Label": label, "ProgramArguments": ["/usr/bin/true"]}))
    domain = f"user/{os.getuid()}"
    control = sbx.run(["/bin/launchctl", "print", domain],
                      profile="(version 1)(allow default)", discard=True)
    assert control.returncode == 0, "launchd domain unavailable; not denial evidence"
    try:
        result = sbx.run(["/bin/launchctl", "bootstrap", domain, str(job)], discard=True)
        assert result.returncode != 0
        read = subprocess.run(["/bin/launchctl", "print", f"{domain}/{label}"], env=sbx.env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        assert read.returncode != 0
    finally:
        # Removal is limited to this test's unique label, even after a timeout/failure.
        subprocess.run(["/bin/launchctl", "bootout", f"{domain}/{label}"], env=sbx.env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


@pytest.mark.macos
@macos
def test_unlisted_unix_socket_is_refused_in_every_network_mode(sbx):
    # A short path also works with AF_UNIX's 104-byte path limit on macOS.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="sbx-", dir="/private/tmp") as directory:
        path = directory + "/agent"
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(path)
            listener.listen(8)
            source = """
import errno, socket, sys
with socket.socket(socket.AF_UNIX) as sock:
    try:
        sock.connect(sys.argv[1])
    except OSError as exc:
        print(exc.errno)
    else:
        print(0)
"""
            control = sbx.python(source, path, profile="(version 1)(allow default)")
            assert control.returncode == 0 and control.stdout.strip() == "0", control.stderr
            for mode in NetworkMode:
                sbx.network = mode
                result = sbx.python(source, path)
                assert result.returncode == 0, result.stderr
                assert int(result.stdout) in (errno.EPERM, errno.EACCES)


@pytest.mark.macos
@macos
def test_read_write_and_protected_paths(sbx):
    readable = sbx.root / "readable"
    readable.write_text("public")
    secret = sbx.protected / "secret"
    secret.write_text("private")
    source = """
from pathlib import Path
import errno, sys
assert Path(sys.argv[1]).read_text() == 'public'
Path('allowed').write_text('ok')
for path, action in ((sys.argv[1], 'write'), (sys.argv[2], 'read'), (sys.argv[2], 'write')):
    try:
        Path(path).read_text() if action == 'read' else Path(path).write_text('bad')
    except OSError as exc:
        assert exc.errno in (errno.EPERM, errno.EACCES), exc
    else:
        raise AssertionError('boundary allowed')
print('checked')
"""
    result = sbx.python(source, readable, secret)
    assert result.returncode == 0 and result.stdout.strip() == "checked", result.stderr
    assert readable.read_text() == "public" and secret.read_text() == "private"


@pytest.mark.macos
@macos
def test_same_sandbox_signals_and_pty(sbx):
    result = sbx.python("""
import os, pty, signal, subprocess, sys
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])
child.send_signal(signal.SIGTERM)
assert child.wait(timeout=5) == -signal.SIGTERM
master, slave = pty.openpty()
os.write(slave, b'sbx')
assert os.read(master, 3) == b'sbx'
os.close(master)
os.close(slave)
print('checked')
""")
    assert result.returncode == 0 and result.stdout.strip() == "checked", result.stderr
    # The external target belongs to this test. If confinement regresses, only
    # this disposable sleeper receives the signal, never pytest or another app.
    with subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(30)"],
                          env=sbx.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as outside:
        try:
            denied = sbx.python("""
import errno, os, signal, sys
try:
    os.kill(int(sys.argv[1]), signal.SIGTERM)
except OSError as exc:
    assert exc.errno == errno.EPERM, exc
else:
    raise AssertionError('signal outside sandbox allowed')
""", outside.pid)
            assert denied.returncode == 0, denied.stderr
            assert outside.poll() is None
        finally:
            outside.kill()
            outside.wait()


@pytest.mark.macos
@macos
def test_posix_ipc_is_confined_to_the_run_prefix(sbx):
    source = """
import ctypes as C, errno, os
lib = C.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
lib.sem_open.restype = C.c_void_p
lib.sem_open.argtypes = [C.c_char_p, C.c_int]
lib.sem_close.argtypes = [C.c_void_p]
lib.sem_unlink.argtypes = [C.c_char_p]
lib.shm_open.argtypes = [C.c_char_p, C.c_int, C.c_int]
for prefix, allowed in ((os.environ['SBX_IPC_PREFIX'], True), ('/sbx-other-', False)):
    name = (prefix + 'x').encode()
    fd = lib.shm_open(name, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    error = C.get_errno()
    if fd >= 0:
        os.close(fd)
        lib.shm_unlink(name)
    assert (fd >= 0) == allowed, ('shm', fd, error)
    if not allowed:
        assert error in (errno.EPERM, errno.EACCES), error
    sem = lib.sem_open(name, os.O_CREAT | os.O_EXCL, C.c_uint(0o600), C.c_uint(1))
    error = C.get_errno()
    # Darwin SEM_FAILED is (sem_t *)-1.
    success = sem != C.c_void_p(-1).value
    if success:
        lib.sem_close(sem)
        lib.sem_unlink(name)
    assert success == allowed, ('sem', error)
    if not allowed:
        assert error in (errno.EPERM, errno.EACCES), error
print('checked')
"""
    result = sbx.python(source)
    assert result.returncode == 0 and result.stdout.strip() == "checked", result.stderr


@pytest.mark.macos
@macos
def test_apple_events_refused_without_contacting_an_app(sbx):
    result = sbx.run(["/usr/bin/osascript", "-e",
                      'tell application id "com.arslan.sbx-probe.nonexistent" to get name'], discard=True)
    assert result.returncode != 0
    # A missing application is not proof: ask the kernel for the operation too.
    check = sbx.python("""
import ctypes as C, os
lib = C.CDLL('/usr/lib/libsandbox.dylib')
lib.sandbox_check.argtypes = [C.c_int, C.c_char_p, C.c_int]
flag = C.c_int.in_dll(lib, 'SANDBOX_CHECK_NO_REPORT').value
assert lib.sandbox_check(os.getpid(), b'appleevent-send', flag) == 1
""")
    assert check.returncode == 0, check.stderr


@pytest.mark.macos
@macos
@pytest.mark.parametrize("mode", [NetworkMode.PROXY, NetworkMode.ANY_DECLARED, NetworkMode.PORT_22])
def test_loopback_listener_and_arslan_port_exclusion(sbx, mode):
    sbx.network = mode
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        port = listener.getsockname()[1]
        source = """
import errno, socket, sys
with socket.socket() as sock:
    try:
        sock.connect(('127.0.0.1', int(sys.argv[1])))
    except OSError as exc:
        print(exc.errno)
    else:
        print(0)
"""
        allowed = sbx.python(source, port)
        assert allowed.returncode == 0 and allowed.stdout.strip() == "0", allowed.stderr
        denied = sbx.python(source, port, profile=sbx.profile(denied_ports=[port]))
        assert denied.returncode == 0, denied.stderr
        assert int(denied.stdout) in (errno.EPERM, errno.EACCES)
    result = sbx.python("""
import errno, socket
with socket.socket() as server:
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    with socket.create_connection(server.getsockname(), timeout=3) as client:
        peer, _ = server.accept()
        with peer:
            client.sendall(b'x')
            assert peer.recv(1) == b'x'
with socket.socket() as server:
    try:
        server.bind(('0.0.0.0', 0))
    except OSError as exc:
        assert exc.errno in (errno.EPERM, errno.EACCES), exc
    else:
        raise AssertionError('all-interface bind allowed')
""")
    assert result.returncode == 0, result.stderr


@pytest.mark.macos
@macos
def test_device_writes_are_narrow(sbx):
    result = sbx.python("""
import errno, os
for path in ('/dev/null', '/dev/zero'):
    fd = os.open(path, os.O_WRONLY)
    os.write(fd, b'x')
    os.close(fd)
# Open only, never write to a non-allowlisted device, even if the rule regresses.
try:
    fd = os.open('/dev/random', os.O_WRONLY)
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES), exc
else:
    os.close(fd)
    raise AssertionError('unlisted device writable')
""")
    assert result.returncode == 0, result.stderr
