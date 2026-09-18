"""Cooperative process lock for the packaged backend and offline maintenance.

The lock file contains no PID, token or user content. OS ownership, not the
presence of the file, decides whether a profile is busy. Does not stop processes
or protect against older/uncooperative binaries that do not take this lock.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import stat


@contextmanager
def hold(database: Path):
    if os.name != "posix":
        raise ValueError("data_profile_lock_platform_unavailable")
    import fcntl

    database = database.resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    path = database.with_name(f".{database.name}.arslan-lock")
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        fd = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077):
            raise ValueError("data_profile_lock_unsafe")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("data_profile_in_use") from exc
        yield
    finally:
        # Do NOT unlink: another process may already hold an open descriptor.
        # Keeping one stable inode avoids creating two independent lock domains.
        os.close(fd)
