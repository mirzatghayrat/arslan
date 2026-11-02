"""Receiver/file-backed SBX-4 gates; only registered adapters satisfy them.

Must go red: K1 remove compute exec denial; K2 grant runtime writes;
K3 grant foreign POSIX shared memory; K4 grant the interpreter's bin directory.
"""
import ctypes
import os
from pathlib import Path
import shutil
import sys
import uuid

import pytest

from server.services.sandbox_profile import NetworkMode
from tests.server.sbx.test_sbx4_presets import pending

macos = pytest.mark.skipif(sys.platform != "darwin", reason="macOS seatbelt")
compute = pytest.mark.parametrize("sbx", [pytest.param(b, marks=pending(b))
                                         for b in ("run-python", "artifact")], indirect=True)
mcp = pytest.mark.parametrize("sbx,mode", [
    pytest.param(base, mode, marks=pending(base), id=base + "-" + mode.value)
    for base, mode in (("mcp", NetworkMode.NONE), ("mcp-proxy", NetworkMode.PROXY))], indirect=["sbx"])


def checked_refusal(sbx, source, *args, profile=None, python=sys.executable):
    control = sbx.run([python, "-I", "-c", source, *map(str, args), "control"], profile="(version 1)(allow default)",
                         probe="boundary-control")
    assert control.returncode == 0, control.stderr
    result = sbx.run([python, "-I", "-c", source, *map(str, args), "deny"], profile=profile, probe="boundary-denial")
    assert result.returncode == 0, result.stderr


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@compute
@pytest.mark.parametrize("method", ["shell", "binary", "posix-spawn", "shebang"])
def test_compute_cannot_start_another_program(sbx, method):
    script = sbx.work / "script"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    checked_refusal(sbx, """
import errno, os, subprocess, sys
method, script, expect = sys.argv[1:]
argv = {'shell': ['/bin/sh', '-c', 'exit 0'], 'binary': ['/usr/bin/true'],
        'posix-spawn': ['/usr/bin/true'], 'shebang': [script]}[method]
try:
    if method == 'posix-spawn':
        pid = os.posix_spawn(argv[0], argv, os.environ)
        _, status = os.waitpid(pid, 0)
        assert status == 0
    else:
        assert subprocess.run(argv, check=False).returncode == 0
except OSError as exc:
    assert expect == 'deny' and exc.errno in (errno.EPERM, errno.EACCES), exc
else:
    assert expect == 'control', 'another program executed'
""", method, script)


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@compute
def test_compute_cannot_execute_interpreter_sibling(sbx):
    # A disposable bin directory, never a write to the installed interpreter.
    runtime = sbx.root / "runtime" / "bin"
    runtime.mkdir(parents=True)
    interpreter = runtime / "python"
    interpreter.symlink_to(Path(sys.executable).resolve())
    sibling = runtime / "sibling"
    shutil.copy("/usr/bin/true", sibling)
    profile = sbx.profile(python=str(interpreter))
    checked_refusal(sbx, """
import errno, subprocess, sys
try:
    assert subprocess.run([sys.argv[1]], check=False).returncode == 0
except OSError as exc:
    assert sys.argv[2] == 'deny' and exc.errno in (errno.EPERM, errno.EACCES), exc
else:
    assert sys.argv[2] == 'control', 'interpreter sibling executed'
""", sibling, profile=profile, python=str(interpreter))


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@mcp
@pytest.mark.parametrize("kind", ["runtime-library", "shared-interpreter"])
def test_mcp_runtime_is_read_only(sbx, mode, kind):
    runtime = sbx.root / "shared-runtime"
    runtime.mkdir()
    target = runtime / kind
    target.write_text("original")
    profile = sbx.profile(read=[str(runtime)])
    source = """
import errno, pathlib, sys
p = pathlib.Path(sys.argv[1])
assert p.read_text() == 'original'
try:
    p.write_text('changed')
except OSError as exc:
    assert sys.argv[2] == 'deny' and exc.errno in (errno.EPERM, errno.EACCES), exc
else:
    assert sys.argv[2] == 'control', 'shared runtime changed'
"""
    control = sbx.python(source, target, "control", profile="(version 1)(allow default)", probe="runtime-write-control")
    assert control.returncode == 0 and target.read_text() == "changed", control.stderr
    target.write_text("original")
    result = sbx.python(source, target, "deny", profile=profile, probe="runtime-write-denial")
    assert target.read_text() == "original", "shared runtime changed"
    assert result.returncode == 0, result.stderr


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@mcp
def test_mcp_cannot_open_foreign_shared_memory(sbx, mode):
    lib = ctypes.CDLL(None, use_errno=True)
    lib.shm_open.argtypes = [ctypes.c_char_p, ctypes.c_int]
    name = ("/sbx-" + uuid.uuid4().hex[:20]).encode()
    fd = lib.shm_open(name, os.O_CREAT | os.O_EXCL | os.O_RDWR, ctypes.c_uint(0o600))
    assert fd >= 0, ctypes.get_errno()
    try:
        os.ftruncate(fd, 16)
        checked_refusal(sbx, """
import ctypes, errno, os, sys
lib = ctypes.CDLL(None, use_errno=True)
lib.shm_open.argtypes = [ctypes.c_char_p, ctypes.c_int]
fd = lib.shm_open(sys.argv[1].encode(), os.O_RDWR, ctypes.c_uint(0))
if fd >= 0:
    os.close(fd)
    assert sys.argv[2] == 'control', 'foreign shared memory opened'
else:
    assert sys.argv[2] == 'deny' and ctypes.get_errno() in (errno.EPERM, errno.EACCES), (sys.argv[2], ctypes.get_errno())
""", name.decode())
    finally:
        os.close(fd)
        lib.shm_unlink(name)
