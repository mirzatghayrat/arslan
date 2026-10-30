"""Compatibility measurements, not acceptance claims. See README.md for result properties."""
import subprocess
import sys
import plistlib
from dataclasses import dataclass

import pytest

from server.services.sandbox_profile import NetworkMode
from tests.server.sbx.harness import MEASUREMENT_BASES, base_parameter

macos = pytest.mark.skipif(sys.platform != "darwin", reason="macOS seatbelt")


@dataclass(frozen=True)
class Case:
    name: str
    argv: tuple[str, ...]
    online: bool = False


def shell(name, source, online=False):
    return Case(name, ("/bin/bash", "-p", "-c", "set -eu\n" + source), online)


def python(name, source, online=False):
    return Case(name, (sys.executable, "-I", "-c", source), online)


CASES = [
    Case("user-lookup", ("/usr/bin/id", "-un")),
    shell("preference-read", 'defaults read "$SBX_PREF_DOMAIN" probe'),
    Case("git-version", ("git", "--version")),
    shell("git-local", "git init -q repo; cd repo; printf sbx > file; git add file; "
          "git -c user.name=SBX -c user.email=sbx@example.invalid -c commit.gpgsign=false "
          "commit -qm probe; git branch probe; git log --oneline"),
    shell("git-clone-https", "git -c credential.helper= clone --depth=1 "
          "https://github.com/octocat/Hello-World.git clone", True),
    # No stored credential can match this unique .invalid host. Output is discarded.
    shell("git-keychain-helper", "printf 'protocol=https\\nhost=com.arslan.sbx-probe.invalid\\n\\n' | "
          "git credential-osxkeychain get > /dev/null", True),
    # Controlled absent local endpoint, never a real remote or real key.
    shell("ssh-remote", "GIT_SSH_COMMAND='ssh -F /dev/null -o BatchMode=yes -o IdentityAgent=none "
          "-o IdentityFile=none -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=yes "
          "-o ConnectTimeout=2 -p 1' git ls-remote ssh://127.0.0.1/probe", True),
    Case("python-version", (sys.executable, "--version")),
    python("python-compute", "assert sum(range(100)) == 4950"),
    Case("python-venv", (sys.executable, "-I", "-m", "venv", "venv")),
    shell("pip-download", "python -m venv pip-env; pip-env/bin/python -m pip download "
          "--disable-pip-version-check --no-deps --dest downloads six==1.17.0", True),
    Case("node-version", ("node", "--version")),
    Case("node-script", ("node", "-e", "if (2+2 !== 4) process.exit(1)")),
    Case("node-watch", ("node", "-e", "const fs=require('fs'); fs.mkdirSync('watch'); "
                       "const w=fs.watch('watch',()=>{w.close();process.exit(0)}); "
                       "fs.writeFileSync('watch/a','x');setTimeout(()=>process.exit(2),3000)")),
    Case("node-workers", ("node", "-e", "const {Worker}=require('worker_threads'); "
                         "new Worker('2+2',{eval:true}).on('error',()=>process.exit(1))")),
    Case("npm-view", ("npm", "view", "is-number@7.0.0", "version", "--ignore-scripts"), True),
    Case("sdk-path", ("xcrun", "--show-sdk-path")),
    Case("swift-version", ("swift", "--version")),
    shell("swiftc", "printf 'print(42)\\n' > main.swift; swiftc main.swift -o hello; ./hello"),
    shell("swift-package", "mkdir package; cd package; swift package init --type executable; swift build"),
    Case("brew-version", ("brew", "--version")),
    Case("brew-prefix", ("brew", "--prefix")),
    Case("brew-list", ("brew", "list", "--versions")),
    Case("brew-info", ("brew", "info", "--json=v2", "--installed")),
    python("dns", "import socket; assert socket.getaddrinfo('example.com', 443)", True),
    Case("curl-certificate", ("curl", "--fail", "--silent", "--max-time", "10",
                              "--output", "/dev/null", "https://example.com"), True),
    python("python-certificate", "import urllib.request; urllib.request.urlopen('https://example.com', timeout=10).close()", True),
    shell("git-certificate", "git -c credential.helper= ls-remote https://github.com/octocat/Hello-World.git HEAD", True),
    shell("swift-certificate", "swift fetch.swift", True),
    Case("zsh", ("/bin/zsh", "-f", "-c", "printf sbx > zsh-output")),
    Case("bash", ("/bin/bash", "-p", "-c", "printf sbx > bash-output")),
    python("multiprocessing", "import multiprocessing as m\nwith m.get_context('fork').Pool(2) as p:\n assert p.map(abs, [-1,-2]) == [1,2]"),
    python("pty", "import os,pty; a,b=pty.openpty(); os.close(a); os.close(b)"),
    python("tempfile", "import os,tempfile; f=tempfile.NamedTemporaryFile(); assert f.name.startswith(os.environ['TMPDIR'])"),
    shell("mktemp", "p=$(mktemp); rm \"$p\""),
    shell("mktemp-template", "p=$(mktemp -t arslan-sbx-probe); rm \"$p\""),
    python("hardcoded-tmp", "import os,tempfile; fd,p=tempfile.mkstemp(prefix='arslan-sbx-', dir='/tmp'); os.close(fd); os.unlink(p)"),
    python("darwin-user-temp", "import os,tempfile; d=os.confstr('CS_DARWIN_USER_TEMP_DIR'); "
           "fd,p=tempfile.mkstemp(prefix='arslan-sbx-', dir=d); os.close(fd); os.unlink(p)"),
    python("darwin-user-cache", "import os,tempfile; d=os.confstr('CS_DARWIN_USER_CACHE_DIR'); "
           "fd,p=tempfile.mkstemp(prefix='arslan-sbx-', dir=d); os.close(fd); os.unlink(p)"),
    shell("pip-cache-two-runs", "python -m venv pip-env; pip-env/bin/python -m pip download "
          "--disable-pip-version-check --no-deps --dest downloads six==1.17.0; "
          "pip-env/bin/python -m pip download --disable-pip-version-check "
          "--no-deps --dest downloads-again six==1.17.0", True),
    shell("npm-cache-two-runs", "npm cache add is-number@7.0.0 --ignore-scripts; "
          "npm cache add is-number@7.0.0 --ignore-scripts", True),
    shell("uv-cache-two-runs", "uv venv first; uv pip install --python first/bin/python six==1.17.0; "
          "uv venv second; uv pip install --python second/bin/python six==1.17.0", True),
]
PARAMETERS = [pytest.param(case, mode, id=case.name + "-" + mode.value)
              for case in CASES
              for mode in ([NetworkMode.NONE, NetworkMode.PROXY, NetworkMode.ANY_DECLARED]
                           if case.online else [NetworkMode.NONE])]


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("sbx", [base_parameter(n) for n in MEASUREMENT_BASES], indirect=True)
@pytest.mark.parametrize("case,mode", PARAMETERS)
def test_compatibility_measurement(sbx, case, mode, record_property):
    sbx.network = mode
    # Foundation fetch waits at most 10 seconds and prints neither response nor errors.
    (sbx.work / "fetch.swift").write_text('''import Foundation
let done = DispatchSemaphore(value: 0)
var ok = false
URLSession.shared.dataTask(with: URL(string: "https://example.com")!) { _, response, error in
    ok = error == nil && response != nil
    done.signal()
}.resume()
let finished = done.wait(timeout: .now() + 10) == .success
exit(finished && ok ? 0 : 1)
''')
    domain = "com.arslan.sbx-probe." + sbx.ipc_prefix[8:-1]
    preferences = sbx.home / "Library" / "Preferences"
    preferences.mkdir(parents=True)
    (preferences / (domain + ".plist")).write_bytes(plistlib.dumps({"probe": "sbx"}))
    sbx.env["SBX_PREF_DOMAIN"] = domain
    try:
        version = case.name.endswith("-version")
        result = sbx.run(case.argv, timeout=45, discard=not version)
    except subprocess.TimeoutExpired:
        outcome, code = "timeout", None
    else:
        code = result.returncode
        outcome = "ok" if code == 0 else "tool-failed"
        # sandbox-exec reports a missing executable as a failure. It is not a skip
        # and never evidence that a deny worked; preserve it as a measurement gap.
        import shutil
        if shutil.which(case.argv[0], path=sbx.env["PATH"]) is None:
            outcome = "tool-unavailable"
        if version and code == 0:
            record_property("tool_version", (result.stdout or result.stderr).splitlines()[0])
    record_property("probe", case.name)
    record_property("outcome", outcome)
    record_property("returncode", code)
    # This row records compatibility/card cost; the kernel tests are hard gates.
    # Raw stdout/stderr is intentionally not retained (credential helpers included).


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("sbx", [base_parameter(n) for n in MEASUREMENT_BASES], indirect=True)
def test_hardlink_measurement(sbx, record_property):
    target = sbx.root / "outside-file"
    target.write_text("original")
    result = sbx.python("""
import errno, os, pathlib, sys
try:
    os.link(sys.argv[1], 'alias')
    pathlib.Path('alias').write_text('changed')
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES), exc
    print('refused')
else:
    print('writable')
""", target)
    assert result.returncode == 0, result.stderr
    record_property("outcome", "boundary-open" if target.read_text() != "original" else "refused")
    # SBX-M must open a follow-up before SBX-3 if the candidate says boundary-open.


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("sbx", [base_parameter(n) for n in MEASUREMENT_BASES], indirect=True)
def test_background_child_measurement(sbx, record_property):
    result = sbx.python("""
import os, subprocess, sys
child = subprocess.Popen([sys.executable, '-I', '-c',
    "import pathlib,time,os; time.sleep(.1); pathlib.Path(os.environ['TMPDIR'],'child').write_text('ok')"])
assert child.wait(timeout=5) == 0
""")
    record_property("outcome", "ok" if result.returncode == 0 else "tool-failed")
    # This tests child access, not the SBX-3 Run lifetime/boot sweep (not built yet).


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("sbx", [base_parameter(n) for n in MEASUREMENT_BASES], indirect=True)
@pytest.mark.parametrize("kind", ["ssh-agent", "gpg-agent", "docker"])
def test_real_socket_reachability(sbx, kind, record_property):
    import os
    # SBX-M's operator supplies exactly the socket to measure; no discovery of
    # private folders and no protocol bytes, credential requests or Docker calls.
    path = os.environ.get("SBX_" + kind.upper().replace("-", "_") + "_SOCKET")
    if path is None:
        record_property("outcome", "not-supplied")
        return
    sbx.network = NetworkMode.ANY_DECLARED
    result = sbx.python("""
import socket, sys
with socket.socket(socket.AF_UNIX) as sock:
    sock.settimeout(2)
    try:
        sock.connect(sys.argv[1])
    except OSError as exc:
        print(exc.errno)
    else:
        print(0)
""", path)
    assert result.returncode == 0, result.stderr
    record_property("connect_errno", int(result.stdout))
    record_property("outcome", "reachable" if int(result.stdout) == 0 else "unreachable")
