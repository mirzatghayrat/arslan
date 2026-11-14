"""NET-a (Codex round 1, F1): whose processes hold the other end of a connection to Arslan's sandbox proxy.

A token names the run a connection claims to be (`net_policy.run_for`); this checks the claim, so a token read from a
file, a log or an environment is no use to a process that isn't that run's. The proxy listens on 127.0.0.1 only, so
the client's end of each connection is a TCP socket from 127.0.0.1:<its port> to 127.0.0.1:<the proxy's port>, held by
the process that connected (and any process it shared the socket with).

A run's processes (`members`): the one Arslan started for it (its root, which leads a session of its own:
start_new_session, for a command and for an MCP server alike), every process still in that session, and every
descendant of one of those (a child that started a session of its own while its parent ran, such as a build daemon).
A process can't join a session other than its own or become the descendant of a process that didn't start it, so another
run's process is never one, and nor is one that left this run and lost its parent (a double fork re-parents it to
launchd, outside the session): that one's connections are refused.

macOS reads the process table and the candidates' sockets through libproc (the calls lsof and psutil make), Linux
through /proc. Whatever can't be read holds nothing: the connection is refused.

Known limit: the table is read anew for each connection, by pid. A pid whose process and session are gone could be
given to a new process; a command's run ends as its process exits, but an MCP server's run ends when its session
notices, so for that while a new process given the pid would count as the server's (the kernel hands pids out in
order, so it would take the whole range coming round first).
"""
from __future__ import annotations

import ctypes
import functools
import logging
import os
import socket
import struct
import sys

logger = logging.getLogger(__name__)

_LOOPBACK = socket.inet_aton("127.0.0.1")
#: What can come before 127.0.0.1's four bytes in an address field: nothing (Linux's IPv4 rows), an IPv4 address in
#: libproc's 16 bytes, or IPv4-mapped IPv6 (a dual-stack client's socket, such as Java's).
_PREFIXES = (b"", bytes(12), bytes(10) + b"\xff\xff")


def _is_loopback(raw: bytes) -> bool:
    return raw[-4:] == _LOOPBACK and raw[:-4] in _PREFIXES


def held(root: int | None, client, server) -> bool:
    """Whether the client end of the proxy's connection from `client` to `server` ((host, port) each, as the proxy's
    socket names its peer and itself) is held by a process of the run whose root process is `root`."""
    if not root or root <= 1 or not client or not server or client[0] != "127.0.0.1" or server[0] != "127.0.0.1":
        return False
    try:
        if sys.platform == "darwin":
            return _darwin_holds(members(_darwin_table(), root), client[1], server[1])
        if sys.platform.startswith("linux"):
            return _linux_holds(members(_linux_table(), root), client[1], server[1])
    except Exception as exc:  # noqa: BLE001 — what can't be read holds nothing: the connection is refused
        logger.warning("sandbox proxy: can't tell which process holds a connection (%s); it is refused", exc)
    return False


def members(table: dict[int, tuple[int, int]], root: int) -> set[int]:
    """The run of `root` in a process table of {pid: (parent pid, session id)}: `root`, its session, and every
    descendant of a process in either."""
    children: dict[int, list[int]] = {}
    for pid, (parent, _) in table.items():
        children.setdefault(parent, []).append(pid)
    found: set[int] = set()
    todo = [pid for pid, (_, session) in table.items() if session == root or pid == root]
    while todo:
        pid = todo.pop()
        if pid not in found:
            found.add(pid)
            todo.extend(children.get(pid, ()))
    return found


# ── macOS: libproc (<sys/proc_info.h>, unchanged since macOS 10.7) ───────────

_UID_ONLY, _LIST_FDS, _SHORT_BSD_INFO, _SOCKET_INFO = 4, 1, 13, 3      # proc_listpids / proc_pidinfo flavors
_FD_SOCKET, _TCP = 2, 2                                                 # PROX_FDTYPE_SOCKET, SOCKINFO_TCP
#: struct proc_bsdshortinfo: 64 bytes, pbsi_ppid at 4. struct socket_fdinfo: 792 bytes, with psi.soi_kind at 256, then
#: the TCP socket's foreign and local ports (each an int, network order) at 264 and 268, and its foreign and local
#: addresses (16 bytes each) at 296 and 312 (offsetof, macOS 26 SDK; the same layout on arm64 and x86_64).
_SHORT_INFO_SIZE, _PARENT = 64, 4
_SOCKET_INFO_SIZE, _KIND, _PORTS, _FOREIGN, _LOCAL = 792, 256, 264, 296, 312


@functools.cache
def _libproc():
    lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    lib.proc_listpids.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidfdinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    return lib


def _darwin_table() -> dict[int, tuple[int, int]]:
    """This user's processes: {pid: (parent pid, session id)}. A run's processes run as the user who runs Arslan."""
    lib = _libproc()
    uid = os.getuid()
    size = lib.proc_listpids(_UID_ONLY, uid, None, 0)
    pids = (ctypes.c_int * (max(size, 0) // 4 + 64))()
    size = lib.proc_listpids(_UID_ONLY, uid, pids, ctypes.sizeof(pids))
    info = ctypes.create_string_buffer(_SHORT_INFO_SIZE)
    table = {}
    for pid in pids[:max(size, 0) // 4]:
        if pid <= 0 or lib.proc_pidinfo(pid, _SHORT_BSD_INFO, 0, info, _SHORT_INFO_SIZE) != _SHORT_INFO_SIZE:
            continue
        try:
            table[pid] = (struct.unpack_from("=I", info.raw, _PARENT)[0], os.getsid(pid))
        except OSError:                                  # gone meanwhile
            continue
    return table


def _darwin_holds(pids, port: int, server_port: int) -> bool:
    """Whether one of `pids` holds a TCP socket from 127.0.0.1:`port` to 127.0.0.1:`server_port`."""
    lib = _libproc()
    info = ctypes.create_string_buffer(_SOCKET_INFO_SIZE)
    for pid in pids:
        size = lib.proc_pidinfo(pid, _LIST_FDS, 0, None, 0)
        if size <= 0:
            continue
        fds = ctypes.create_string_buffer(size + 64 * 8)               # room for files it opened meanwhile
        size = lib.proc_pidinfo(pid, _LIST_FDS, 0, fds, len(fds))
        for fd, kind in struct.iter_unpack("=iI", fds.raw[:max(size, 0) // 8 * 8]):     # struct proc_fdinfo
            if (kind != _FD_SOCKET
                    or lib.proc_pidfdinfo(pid, fd, _SOCKET_INFO, info, _SOCKET_INFO_SIZE) != _SOCKET_INFO_SIZE):
                continue
            raw = info.raw
            if struct.unpack_from("=i", raw, _KIND)[0] != _TCP:
                continue
            foreign, local = (socket.ntohs(value & 0xFFFF) for value in struct.unpack_from("=ii", raw, _PORTS))
            if ((local, foreign) == (port, server_port) and _is_loopback(raw[_FOREIGN:_FOREIGN + 16])
                    and _is_loopback(raw[_LOCAL:_LOCAL + 16])):
                return True
    return False


# ── Linux: /proc ─────────────────────────────────────────────────────────────

def _linux_table(proc: str = "/proc") -> dict[int, tuple[int, int]]:
    """Every process: {pid: (parent pid, session id)}, from /proc/<pid>/stat (its fields after the name: state, parent,
    process group, session)."""
    table = {}
    for name in os.listdir(proc):
        if not name.isdigit():
            continue
        try:
            with open(os.path.join(proc, name, "stat"), "rb") as stat:
                fields = stat.read().rpartition(b")")[2].split()
            table[int(name)] = (int(fields[1]), int(fields[3]))
        except (OSError, IndexError, ValueError):        # gone meanwhile
            continue
    return table


def _linux_end(text: str) -> tuple[bytes, int]:
    """One end of a /proc/net/tcp row: the address (the kernel writes each 32-bit word in host order) and the port."""
    address, _, port = text.partition(":")
    raw = b"".join(struct.pack("=I", int(address[i:i + 8], 16)) for i in range(0, len(address), 8))
    return raw, int(port, 16)


def _linux_holds(pids, port: int, server_port: int, proc: str = "/proc") -> bool:
    """Whether one of `pids` holds a TCP socket from 127.0.0.1:`port` to 127.0.0.1:`server_port`: the socket's inode in
    /proc/net/tcp (or tcp6), among the sockets in their /proc/<pid>/fd."""
    wanted = set()
    for table in ("tcp", "tcp6"):
        try:
            with open(os.path.join(proc, "net", table)) as rows:
                lines = rows.read().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10:
                continue
            (local, local_port), (foreign, foreign_port) = _linux_end(fields[1]), _linux_end(fields[2])
            if ((local_port, foreign_port) == (port, server_port) and _is_loopback(local)
                    and _is_loopback(foreign)):
                wanted.add(f"socket:[{fields[9]}]")
    for pid in pids if wanted else ():
        folder = os.path.join(proc, str(pid), "fd")
        try:
            fds = os.listdir(folder)
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(os.path.join(folder, fd)) in wanted:
                    return True
            except OSError:
                continue
    return False
