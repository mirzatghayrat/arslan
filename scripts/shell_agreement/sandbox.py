"""One command, run by the real shell inside bubblewrap, with what it started recorded."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from scripts.shell_agreement import stubs

#: Program directories replaced by the stubs. /bin and /sbin are bound only where they are real
#: directories (on a merged-/usr system they are symlinks into /usr and need nothing).
PROGRAM_DIRS = ("/usr/bin", "/usr/sbin", "/usr/local/bin", "/usr/local/sbin", "/bin", "/sbin")
MAC_PROGRAM_DIRS = ("/opt/homebrew/bin", "/opt/homebrew/sbin", "/opt/local/bin")
PATH_INSIDE = ":".join(PROGRAM_DIRS + MAC_PROGRAM_DIRS)
HOME_INSIDE = "/home/me"
TRACE_INSIDE = "/run/trace/log"
DEFAULT_TIMEOUT_S = 5.0


class Unavailable(RuntimeError):
    """This machine cannot run the comparison (not Linux, no bwrap, or no user namespaces)."""


@dataclass(frozen=True)
class Started:
    program: str                 # as the shell started it ($0 of the stub, usually a full path)
    args: tuple[str, ...]

    @property
    def name(self) -> str:
        return self.program.rsplit("/", 1)[-1]


@dataclass
class Run:
    command: str
    stub_exit: int
    started: list[Started] = field(default_factory=list)
    exit_code: int | None = None
    timed_out: bool = False
    stderr: str = ""


def require() -> str:
    """The bwrap binary, or raise Unavailable with the reason. Refuses on macOS whatever is installed:
    the card runs this only on a one-time CI machine or in a Linux container."""
    if sys.platform == "darwin":
        raise Unavailable("the real-shell comparison never runs on a Mac (card S2a-3, who reviews)")
    if not sys.platform.startswith("linux"):
        raise Unavailable(f"the real-shell comparison runs on Linux only, not {sys.platform}")
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise Unavailable("bwrap (bubblewrap) is not installed")
    probe = subprocess.run([bwrap, "--ro-bind", "/", "/", "--unshare-all", "--dev", "/dev", "--proc", "/proc",
                            "/bin/true"], capture_output=True, text=True, timeout=30)
    if probe.returncode != 0:
        raise Unavailable(f"bwrap cannot start a sandbox here: {probe.stderr.strip()[:200]}")
    return bwrap


def _bind_args(stub_dir: Path) -> list[str]:
    args: list[str] = []
    for folder in PROGRAM_DIRS:
        if os.path.isdir(folder) and not os.path.islink(folder):
            args += ["--bind", str(stub_dir), folder]
    args += ["--tmpfs", "/opt"]
    # A login shell (`bash -lc …`) reads the system's startup files, which start programs of their own
    # (Ubuntu's /etc/profile runs locale-check). The comparison is about the command's text, so they
    # are blank here; the user's own startup files are not there anyway ($HOME is empty).
    for startup in ("/etc/profile", "/etc/bash.bashrc", "/etc/bashrc", "/etc/zshenv", "/etc/zprofile"):
        if os.path.isfile(startup):
            args += ["--ro-bind", "/dev/null", startup]
    if os.path.isdir("/etc/profile.d"):
        args += ["--tmpfs", "/etc/profile.d"]
    for folder in MAC_PROGRAM_DIRS:
        args += ["--bind", str(stub_dir), folder]
    return args


def bwrap_argv(bwrap: str, stub_dir: Path, work: Path, trace_dir: Path, *, stub_exit: int,
               command: str) -> list[str]:
    """The sandbox: the host root read-only, every program directory replaced by the stubs, empty
    homes and temp folders, a fresh work folder as $HOME and cwd, no network, no inherited environment."""
    return [bwrap, "--ro-bind", "/", "/", *_bind_args(stub_dir),
            "--tmpfs", "/tmp", "--tmpfs", "/home", "--tmpfs", "/root", "--tmpfs", "/run", "--tmpfs", "/var/tmp",
            "--bind", str(work), HOME_INSIDE, "--bind", str(trace_dir), "/run/trace",
            "--proc", "/proc", "--dev", "/dev",
            "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
            "--clearenv", "--setenv", "PATH", PATH_INSIDE, "--setenv", "HOME", HOME_INSIDE,
            "--setenv", "TMPDIR", HOME_INSIDE, "--setenv", "TERM", "dumb",
            "--setenv", "ARSLAN_TRACE", TRACE_INSIDE, "--setenv", "ARSLAN_STUB_EXIT", str(stub_exit),
            "--chdir", HOME_INSIDE,
            "/bin/bash", "-p", "-c", command]          # exactly terminal_exec._shell()


def parse_trace(text: str) -> list[Started]:
    out = []
    for record in text.split(stubs.RECORD):
        if not record:
            continue
        fields = record.split(stubs.FIELD)
        if fields and fields[-1] == "":
            fields.pop()
        if fields:
            out.append(Started(fields[0], tuple(fields[1:])))
    return out


def run(bwrap: str, stub_dir: Path, command: str, *, stub_exit: int = 0,
        timeout_s: float = DEFAULT_TIMEOUT_S, keep: Path | None = None) -> Run:
    """Run `command` once. The work folder and the trace live in a temporary folder of their own,
    deleted afterwards (or kept under `keep` for a look)."""
    result = Run(command, stub_exit)
    with tempfile.TemporaryDirectory(prefix="shell-agreement-") as tmp:
        work, trace_dir = Path(tmp, "work"), Path(tmp, "trace")
        work.mkdir()
        trace_dir.mkdir()
        argv = bwrap_argv(bwrap, stub_dir, work, trace_dir, stub_exit=stub_exit, command=command)
        try:
            proc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.PIPE, timeout=timeout_s, start_new_session=True)
            result.exit_code = proc.returncode
            result.stderr = proc.stderr.decode("utf-8", "replace")[-2000:]
        except subprocess.TimeoutExpired as exc:
            result.timed_out = True            # bwrap is gone, and with it the pid namespace it made
            result.stderr = (exc.stderr or b"").decode("utf-8", "replace")[-2000:]
        try:
            result.started = parse_trace((trace_dir / "log").read_text("utf-8", "replace"))
        except FileNotFoundError:
            result.started = []
        if keep is not None:
            shutil.copytree(tmp, keep, dirs_exist_ok=True)
    return result
