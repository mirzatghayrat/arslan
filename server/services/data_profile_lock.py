"""Cooperative process lock for the packaged backend and offline maintenance.

The lock file contains no PID, token or user content. OS ownership, not the
presence of the file, decides whether a profile is busy. Does not stop processes
or protect against older/uncooperative binaries that do not take this lock.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat


@contextmanager
def hold(database: Path):
    database = database.resolve()
    with hold_lifecycle(database):
        record = activation_record_path(database)
        if record.exists() or record.is_symlink():
            raise ValueError("data_profile_recovery_required")
        database.parent.mkdir(parents=True, exist_ok=True)
        with _hold_file(database.with_name(f".{database.name}.arslan-lock")):
            yield


@contextmanager
def hold_lifecycle(database: Path):
    if os.name != "posix":
        raise ValueError("data_profile_lock_platform_unavailable")
    database = database.resolve()
    # The outer namespace stays put when the profile directory is moved during
    # activation. Acquire it BEFORE creating that directory: a competing startup
    # must not recreate a temporarily absent active path. Keep the inner lock for
    # interoperability with the preceding packaged version's ownership check.
    outer = lifecycle_path(database)
    outer.parent.mkdir(parents=True, exist_ok=True)
    with _hold_file(outer):
        yield


def activation_record_path(database: Path) -> Path:
    return lifecycle_path(database).with_suffix(".activation.json")


def lifecycle_path(database: Path) -> Path:
    database = database.resolve()
    namespace = os.fsencode(database.parent.name) + b"\0" + os.fsencode(database.name)
    digest = hashlib.sha256(namespace).hexdigest()
    return database.parent.parent / f".arslan-profile-{digest}.lock"


@contextmanager
def _hold_file(path: Path):
    if os.name != "posix":
        raise ValueError("data_profile_lock_platform_unavailable")
    import fcntl

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
