"""A goal's leftover processes, found and ended (L7-5i, #991 max review L1, the user's decision of 11-17).

A command can leave a process running after it returns (`cmd &`, `nohup`, a dev server): `terminal_exec` starts each
command in a session of its own and ends it on a timeout or a stop, not on a normal return (`run_temp` keeps the run's
temp folder for such a process). Before a goal's host check runs a line that declares outputs, such a process could put
the outputs back right after the host removes them, and the host would accept the worker's bytes as its own run's. So
the goal's check ends them first (`goal_checks.run`), and runs nothing while one is left.

Only a process positively the goal's is ever ended (#991 max review r2):
- the members of a recorded process group whose leader is alive and started when that run's own record says (an id
  is not reused while any process of its group is left, so a live leader with the recorded start is the same group);
- any process whose environment carries one of the goal's runs' own TMPDIRs (`run_temp.folder`, one `mkdtemp` per
  run, so no other process has it), which also finds one that left its group (`setsid`) and was reparented;
- what descends from one of those (a live parent's children are its own).
A process in a recorded group that can't be attributed (the leader is gone and its environment doesn't carry the
run's TMPDIR or can't be read; or the record has no start time) is never ended: it is returned, and the goal stops for
review, naming it. A group whose live leader started at another time is someone else's now: left alone.

Not found: a process that left its group, lost its parent, and whose environment can't be read (macOS hides it for its
own platform binaries such as /bin/sh) or no longer carries the TMPDIR. That is the disclosed residual: a full fix runs
the host's check where no leftover process can write.
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


class Unreadable(RuntimeError):
    """The process table couldn't be read: nothing can be said to be gone."""


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    pgid: int
    started: float          # seconds since the epoch
    command: str


def _table() -> list[Proc]:
    """Every live process (zombies write nothing). Raises Unreadable unless this server itself is in it."""
    try:
        out = subprocess.run(["/bin/ps", "-axww", "-o", "pid=,ppid=,pgid=,stat=,lstart=,command="], capture_output=True,
                             text=True, env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"}, check=False, timeout=20).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise Unreadable(str(exc)) from exc
    procs, seen = [], set()
    for line in out.splitlines():
        words = line.split(None, 9)
        if len(words) < 9 or not all(w.isdigit() for w in words[:3]):
            continue
        seen.add(int(words[0]))
        if words[3].startswith("Z"):
            continue
        try:
            started = time.mktime(time.strptime(" ".join(words[4:9]), "%a %b %d %H:%M:%S %Y"))
        except ValueError:
            continue
        procs.append(Proc(int(words[0]), int(words[1]), int(words[2]), started, words[9] if len(words) > 9 else ""))
    if os.getpid() not in seen:
        raise Unreadable("this server is not in the process table")
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
    return _env_tmpdir(buf.raw[:size.value])


def _env_tmpdir(raw: bytes) -> str | None:
    """TMPDIR from a KERN_PROCARGS2 buffer: argc, the exec path and its NUL padding, then exactly argc strings (empty
    ones too), then the environment (#991 max review r2 S3: an empty argument used to shift it)."""
    if len(raw) < 4:
        return None
    argc = struct.unpack("i", raw[:4])[0]
    at = raw.find(b"\0", 4)
    if at < 0:
        return None
    while at < len(raw) and raw[at] == 0:          # the exec path's padding
        at += 1
    for _ in range(argc):                           # each argument, empty ones included
        end = raw.find(b"\0", at)
        if end < 0:
            return None
        at = end + 1
    for entry in raw[at:].split(b"\0"):
        if not entry:
            break
        if entry.startswith(b"TMPDIR="):
            return entry[7:].decode("utf-8", errors="replace")
    return None


def _ours(procs: list[Proc]) -> set[int]:
    """This server and its ancestors: never ended."""
    mine, pid = set(), os.getpid()
    parents = {p.pid: p.ppid for p in procs}
    while pid and pid not in mine:
        mine.add(pid)
        pid = parents.get(pid, 0)
    return mine


def find(groups: dict[int, tuple[float | None, str | None]], tmpdirs: list[Path]) -> tuple[list[Proc], list[Proc]]:
    """(the goal's live processes, the live processes in its recorded groups that can't be attributed). `groups`: each
    recorded group id, with when it started and its command (`run_temp.recorded`)."""
    procs = _table()
    mine, by_pid = _ours(procs), {p.pid: p for p in procs}
    folders = {os.path.realpath(str(path)) for path in tmpdirs}

    def carries(pid: int) -> bool:
        tmp = _tmpdir(pid)
        return tmp is not None and os.path.realpath(tmp.rstrip("/")) in folders
    picked: set[int] = set()
    unknown: set[int] = set()
    for group, (recorded, _command) in groups.items():
        members = [p for p in procs if p.pgid == group]
        if not members:
            continue
        leader = by_pid.get(group)
        if leader is not None and leader.pgid == group:
            if recorded is not None and abs(leader.started - recorded) <= _SAME_START_S:
                picked |= {p.pid for p in members}
            elif recorded is None:
                unknown |= {p.pid for p in members if not carries(p.pid)}
                picked |= {p.pid for p in members if p.pid not in unknown}
            continue                                # a live leader started at another time: someone else's group
        for p in members:                           # the leader is gone: only what carries the run's TMPDIR
            (picked if carries(p.pid) else unknown).add(p.pid)
    for p in procs:
        if p.pid not in picked and p.pid not in mine and carries(p.pid):
            picked.add(p.pid)
    grew = True
    while grew:                                     # and what descends from them
        grew = False
        for p in procs:
            if p.pid not in picked and p.ppid in picked:
                picked.add(p.pid)
                grew = True
    picked -= mine
    return [by_pid[pid] for pid in sorted(picked)], [by_pid[pid] for pid in sorted(unknown - picked - mine)]


def end(groups: dict[int, tuple[float | None, str | None]], tmpdirs: list[Path]) -> tuple[list[Proc], list[Proc]]:
    """End every process `find` attributes to the goal (SIGKILL, by pid), then look again. Returns (what of the goal's
    is still there, what in its recorded groups couldn't be attributed and was left alone); the caller runs nothing
    unless both are empty. Raises Unreadable when the process table can't be read."""
    left, unknown = find(groups, tmpdirs)
    deadline = time.monotonic() + _END_WAIT_S
    while left and time.monotonic() < deadline:
        for p in left:
            try:
                os.kill(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        time.sleep(0.05)
        left, unknown = find(groups, tmpdirs)
    return left, unknown
