"""Live receiver gates for SBX-4, not SBPL rule-order assertions.

Must go red: D1 terminal data grants; D2 PTY grant; D3 terminal ioctl grant;
D4 FSEvents grant; D5 unrestricted signal; D6 external hard-link creation.
Pre-existing hard-link aliases belong to SBX-5p's protected-path lifecycle.
"""
from concurrent.futures import ThreadPoolExecutor
import fcntl
import os
from pathlib import Path
import select
import struct
import sys
import termios
import time
import tty

import pytest

from tests.server.sbx.harness import Harness
from tests.server.sbx.test_sbx4_presets import cases, pending
from tests.server.sbx.test_sbx4_kernel_boundaries import mcp

macos = pytest.mark.skipif(sys.platform != "darwin", reason="macOS seatbelt")


def received(fd):
    return os.read(fd, 1024) if select.select([fd], [], [], 0.15)[0] else b""


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@cases
def test_foreign_terminal_receives_no_output(sbx, mode):
    for control in (True, False):
        master, slave = os.openpty()
        try:
            tty.setraw(slave)
            result = sbx.python("""
import errno, os, sys
try:
    fd = os.open(sys.argv[1], os.O_WRONLY | os.O_NOCTTY)
    try: os.write(fd, b'sbx-terminal-output')
    finally: os.close(fd)
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES), exc
print('completed')
""", os.ttyname(slave), profile="(version 1)(allow default)" if control else None,
                probe="terminal-output-control" if control else "terminal-output-denial")
            assert result.returncode == 0 and result.stdout.strip() == "completed", result.stderr
            assert received(master) == (b"sbx-terminal-output" if control else b""), "foreign terminal received bytes"
        finally:
            os.close(slave)
            os.close(master)


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@mcp
def test_mcp_cannot_consume_foreign_terminal_input(sbx, mode):
    for control in (True, False):
        master, slave = os.openpty()
        try:
            tty.setraw(slave)
            os.write(master, b"sbx-terminal-input")
            assert select.select([slave], [], [], 2)[0]
            result = sbx.python("""
import errno, os, sys
try:
    fd = os.open(sys.argv[1], os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    try: print(repr(os.read(fd, 1024)))
    finally: os.close(fd)
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES), exc
    print('denied')
""", os.ttyname(slave), profile="(version 1)(allow default)" if control else None,
                probe="terminal-input-control" if control else "terminal-input-denial")
            assert result.returncode == 0, result.stderr
            assert received(slave) == (b"" if control else b"sbx-terminal-input"), "foreign input consumed"
            assert result.stdout.strip() == ("b'sbx-terminal-input'" if control else "denied")
        finally:
            os.close(slave)
            os.close(master)


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@cases
def test_no_usable_pseudo_terminal(sbx, mode):
    source = """
import errno, os, sys
try:
    a, b = os.openpty()
except OSError as exc:
    assert sys.argv[1] == 'deny', exc
    print('denied')
else:
    try:
        os.write(b, b'pty-output')
        assert os.read(a, 1024) == b'pty-output'
    finally:
        os.close(a); os.close(b)
    assert sys.argv[1] == 'control', 'usable PTY allocated'
    print('control')
"""
    for control in (True, False):
        result = sbx.python(source, "control" if control else "deny",
                             profile="(version 1)(allow default)" if control else None,
                             probe="pty-allocation-control" if control else "pty-allocation-denial")
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == ("control" if control else "denied")


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@cases
def test_terminal_ioctl_cannot_change_receiver_state(sbx, mode):
    master, slave = os.openpty()
    try:
        before = struct.pack("HHHH", 23, 79, 0, 0)
        after = struct.pack("HHHH", 41, 101, 0, 0)
        for control in (True, False):
            fcntl.ioctl(slave, termios.TIOCSWINSZ, before)
            # Inherit an already-open disposable fd so an open denial cannot
            # hide an ioctl permission. This is stricter than the stdio path.
            result = sbx.run([sys.executable, "-I", "-c", """
import errno, fcntl, struct, sys, termios
try:
    fcntl.ioctl(int(sys.argv[1]), termios.TIOCSWINSZ, struct.pack('HHHH',41,101,0,0))
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES), exc
print('completed')
""", str(slave)], pass_fds=(slave,),
                profile="(version 1)(allow default)" if control else None,
                probe="terminal-ioctl-control" if control else "terminal-ioctl-denial")
            assert result.returncode == 0 and result.stdout.strip() == "completed", result.stderr
            assert fcntl.ioctl(slave, termios.TIOCGWINSZ, before) == (after if control else before), "terminal state changed"
    finally:
        os.close(slave)
        os.close(master)


def wait_for(path):
    deadline = time.monotonic() + 8
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert path.exists(), "sandbox receiver never became ready"


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@cases
def test_independent_instances_cannot_signal_each_other(sbx, mode):
    other = Harness(sbx.root / "other", sbx.base, mode, executions=sbx.executions)
    if sbx.base == "mcp-proxy":
        other.proxy_port = sbx.proxy_port
    ready, hit, stop = (other.work / name for name in ("ready", "hit", "stop"))
    with ThreadPoolExecutor(max_workers=1) as pool:
        receiver = pool.submit(other.python, """
import os, pathlib, signal, time
signal.signal(signal.SIGUSR1, lambda *_: pathlib.Path('hit').write_text('received'))
pathlib.Path('ready').write_text(str(os.getpid()))
end = time.monotonic() + 15
while not pathlib.Path('stop').exists() and time.monotonic() < end:
    time.sleep(.02)
""", probe="independent-signal-receiver", timeout=20)
        try:
            wait_for(ready)
            pid = ready.read_text()
            source = """
import errno, os, signal, sys
# A forked child inherits this sandbox and must remain controllable.
child = os.fork()
if child == 0:
    signal.pause()
    os._exit(0)
try:
    os.kill(child, signal.SIGTERM)
    assert os.waitpid(child, 0)[1] == signal.SIGTERM
finally:
    try: os.kill(child, signal.SIGKILL)
    except ProcessLookupError: pass
try:
    os.kill(int(sys.argv[1]), signal.SIGUSR1)
except OSError as exc:
    assert sys.argv[2] == 'deny' and exc.errno in (errno.EPERM, errno.EACCES), exc
else:
    assert sys.argv[2] == 'control', 'independent sandbox signalled'
"""
            control = sbx.python(source, pid, "control", profile="(version 1)(allow default)", probe="signal-control")
            assert control.returncode == 0, control.stderr
            wait_for(hit)
            hit.unlink()
            result = sbx.python(source, pid, "deny", probe="signal-denial")
            assert result.returncode == 0, result.stderr
            time.sleep(.1)
            assert not hit.exists(), "other sandbox received signal"
        finally:
            stop.write_text("done")
            result = receiver.result(timeout=22)
            assert result.returncode == 0, result.stderr


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@mcp
def test_mcp_cannot_create_external_hard_link(sbx, mode):
    outside = sbx.root / "outside"
    outside.write_text("original")
    alias = sbx.work / "alias"
    source = """
import errno, os, sys
try:
    os.link(sys.argv[1], sys.argv[2])
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES), exc
print('completed')
"""
    control = sbx.python(source, outside, alias, profile="(version 1)(allow default)", probe="hardlink-control")
    assert control.returncode == 0 and alias.stat().st_ino == outside.stat().st_ino, control.stderr
    alias.unlink()
    result = sbx.python(source, outside, alias, probe="hardlink-denial")
    assert result.returncode == 0 and not alias.exists(), "new external hard link created: " + result.stderr
    assert outside.read_text() == "original"


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("sbx", [pytest.param(base, marks=pending(base))
                                for base in ("run-python", "artifact", "mcp")], indirect=True)
def test_fsevents_reveals_no_external_metadata(sbx):
    import json

    outside = sbx.root / "outside-events"
    outside.mkdir()
    protected = sbx.work / "protected-events"
    protected.mkdir()
    # A broader readable grant makes the Mach service, not missing path reads,
    # the distinguishing control for MCP. Compute keeps its narrower reads.
    profile = sbx.profile(granted_folders=[sbx.root], protected=[protected])
    for control in (True, False):
        ready = sbx.work / "events-ready"
        ready.unlink(missing_ok=True)
        source = (Path(__file__).parent / "corpus" / "fsevents_probe.py").read_text()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(sbx.python, source, sbx.root, ready,
                                 profile="(version 1)(allow default)" if control else profile,
                                 probe="events-control" if control else "events-denial", timeout=12)
            wait_for(ready)
            names = [folder / ("control-event" if control else "denied-event")
                     for folder in (outside, protected)]
            for path in names:
                path.write_text("only disposable data")
            result = future.result(timeout=14)
        assert result.returncode == 0, result.stderr
        rows = json.loads(result.stdout)
        matched = [row for row in rows if any(row[0].rstrip('/') == str(path) for path in names)]
        if control:
            assert {row[0].rstrip('/') for row in matched} == set(map(str, names)), rows
            assert all(row[1] and row[2] for row in matched), rows
        else:
            # No path, flags or event identifier may cross the boundary.
            assert not rows, "external FSEvents metadata delivered: " + repr(rows)
