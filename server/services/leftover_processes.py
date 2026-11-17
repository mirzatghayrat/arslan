"""A run's leftover processes, found and ended (L7-5i, #991 max review L1, the user's decision of 11-17).

A command can leave a process running after it returns (`cmd &`, `nohup`, a dev server): `terminal_exec` starts each
command in a session of its own and ends it on a timeout or a stop, not on a normal return (`run_temp` keeps the run's
temp folder for such a process). Before a goal's host check runs a line that declares outputs, such a process could put
the outputs back right after the host removes them, and the host would accept the worker's bytes as its own run's. So
the goal's check ends them first (`goal_checks.run`), and runs nothing while one is left.

What counts as the run's, as far as the host can tell from what it recorded:
- every live process in a process group a command of the run started (`run_temp.started`);
- every live process descended from one of those (by parent id at the time of the scan);
- every live process whose environment carries the run's own TMPDIR (`run_temp.folder`; one folder per run, so no
  other process has it), which also finds one that left its group (`setsid`) and was reparented.
Not found: a process that left its group, lost its parent, and whose environment can't be read (macOS hides it for
its own platform binaries such as /bin/sh) or no longer carries the TMPDIR. That is the disclosed residual: a full fix
runs the host's check where no leftover process can write.

A recorded group id that the system has since given to someone else's new group is never ended: a group whose leader
is alive and started more than `_SAME_START_S` after or before the recorded start isn't the run's (an id is not reused
while any process of the old group is left).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import signal
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_SAME_START_S = 2.0
_END_WAIT_S = 3.0


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    pgid: int
    started: float          # seconds since the epoch
    command: str


def _table() -> list[Proc]:
    out = subprocess.run(["/bin/ps", "-axww", "-o", "pid=,ppid=,pgid=,stat=,lstart=,command="], capture_output=True,
                         text=True, env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"}, check=False, timeout=20).stdout
    procs = []
    for line in out.splitlines():
        words = line.split(None, 9)
        if len(words) < 9 or not all(w.isdigit() for w in words[:3]) or words[3].startswith("Z"):
            continue                            # a zombie writes nothing
        try:
            started = time.mktime(time.strptime(" ".join(words[4:9]), "%a %b %d %H:%M:%S %Y"))
        except ValueError:
            continue
        procs.append(Proc(int(words[0]), int(words[1]), int(words[2]), started, words[9] if len(words) > 9 else ""))
    return procs


_libc = None


def _tmpdir(pid: int) -> str | None:
    """The process's TMPDIR, read with sysctl(KERN_PROCARGS2) on macOS (/proc on Linux); None when it can't be read
    (another user's process, or a platform binary macOS hides it for)."""
    global _libc
    if not sys.platform.startswith("darwin"):
        try:
            entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        except OSError:
            return None
        return next((e[7:].decode("utf-8", errors="replace") for e in entries if e.startswith(b"TMPDIR=")), None)
    _libc = _libc or ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    mib = (ctypes.c_int * 3)(1, 49, pid)                    # CTL_KERN, KERN_PROCARGS2
    size = ctypes.c_size_t(0)
    if _libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0 or size.value < 4:
        return None
    buf = ctypes.create_string_buffer(size.value)
    if _libc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0:
        return None
    raw = buf.raw[:size.value]
    argc = struct.unpack("i", raw[:4])[0]
    parts = [part for part in raw[4:].split(b"\0") if part]
    for entry in parts[1 + argc:]:
        if entry.startswith(b"TMPDIR="):
            return entry[7:].decode("utf-8", errors="replace")
    return None


def _ours() -> set[int]:
    """This server and its ancestors: never ended."""
    mine, pid = set(), os.getpid()
    parents = {p.pid: p.ppid for p in _table()}
    while pid and pid not in mine:
        mine.add(pid)
        pid = parents.get(pid, 0)
    return mine


def find(groups: dict[int, float | None], tmpdirs: list[Path]) -> list[Proc]:
    """The live processes that are the run's (module docstring). `groups`: each recorded group id and when it was
    started (None: not known, from before this server started)."""
    procs, mine = _table(), _ours()
    by_pid = {p.pid: p for p in procs}
    folders = {os.path.realpath(str(path)) for path in tmpdirs}
    picked: set[int] = set()
    for group, recorded in groups.items():
        leader = by_pid.get(group)
        if leader is not None and leader.pgid == group and (
                recorded is None or abs(leader.started - recorded) > _SAME_START_S):
            continue                            # the id now names another group, or can't be told apart: not ended
        picked |= {p.pid for p in procs if p.pgid == group}
    for p in procs:
        if p.pid not in picked and p.pid not in mine:
            tmp = _tmpdir(p.pid)
            if tmp is not None and os.path.realpath(tmp.rstrip("/")) in folders:
                picked.add(p.pid)
    grew = True
    while grew:                                 # and what descends from them
        grew = False
        for p in procs:
            if p.pid not in picked and p.ppid in picked:
                picked.add(p.pid)
                grew = True
    return [by_pid[pid] for pid in sorted(picked - mine)]


def end(groups: dict[int, float | None], tmpdirs: list[Path]) -> list[Proc]:
    """End every process `find` names (SIGKILL), then look again: what is still there is returned (it couldn't be
    ended, or a new one appeared), and the caller runs nothing."""
    left = find(groups, tmpdirs)
    deadline = time.monotonic() + _END_WAIT_S
    while left and time.monotonic() < deadline:
        for p in left:
            try:
                os.kill(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        time.sleep(0.05)
        left = find(groups, tmpdirs)
    return left
