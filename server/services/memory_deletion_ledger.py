"""Private deletion snapshots independent of the SQLite/backup snapshot.

Post-commit mirror, not a second writable memory store or a disaster backup.
Boot repairs the commit-to-file crash window. Restore must explicitly reconcile
the latest ledger before installation; copying a DB by hand bypasses that flow.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import logging
import os
from pathlib import Path
import stat
import time
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from server.services.memory_deletion_manifest import MAX_BYTES, decode, export_sync

logger = logging.getLogger(__name__)
DIRECTORY = ".memory-deletion-ledgers"


def directory(session) -> Path:
    database = session.get_bind().url.database
    if not database or database == ":memory:":
        raise ValueError("deletion_ledger_requires_file_database")
    return Path(database).absolute().parent / DIRECTORY


def _name(instance_id: str) -> str:
    if str(UUID(instance_id)) != instance_id:
        raise ValueError("invalid_deletion_ledger_identity")
    return instance_id + ".json"


def _private(fd, *, directory=False):
    info = os.fstat(fd)
    valid_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not valid_type or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("unsafe_deletion_ledger_storage")
    if not directory and info.st_nlink != 1:
        raise ValueError("unsafe_deletion_ledger_storage")


@contextmanager
def _root(path: Path, *, create=False):
    # The DB parent is configured by the local operator. Never follow a link in
    # the ledger slot, lock, snapshot or temporary file beneath that parent.
    if os.name != "posix":
        raise OSError("deletion_ledger_platform_unavailable")
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _private(fd, directory=True)
        yield fd
    finally:
        os.close(fd)


def _read(root, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
    with os.fdopen(fd, "rb") as handle:
        _private(handle.fileno())
        if os.fstat(handle.fileno()).st_size > MAX_BYTES:
            raise ValueError("invalid_deletion_manifest")
        return decode(handle.read(MAX_BYTES + 1))


def read(path: Path, instance_id: str) -> dict | None:
    name = _name(instance_id)
    try:
        with _root(path) as root:
            value = _read(root, name)
    except FileNotFoundError:
        return None
    if value["instance_id"] != instance_id:
        raise ValueError("deletion_ledger_store_mismatch")
    return value


def _rows(value):
    return {tuple(sorted(row.items())) for row in value["deletions"]}


def persist(path: Path, payload: bytes) -> str:
    if os.name != "posix":
        raise OSError("deletion_ledger_platform_unavailable")
    import fcntl

    value = decode(payload)
    name = _name(value["instance_id"])
    temporary = ".pending-" + str(uuid4())
    with _root(path, create=True) as root:
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            lock = os.open(name + ".lock", os.O_CREAT | os.O_EXCL | flags, 0o600, dir_fd=root)
        except FileExistsError:
            lock = os.open(name + ".lock", flags, dir_fd=root)
        try:
            _private(lock)
            deadline = time.monotonic() + 1
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise OSError("deletion_ledger_busy") from None
                    time.sleep(0.01)
            try:
                old = _read(root, name)
            except FileNotFoundError:
                old = None
            if old is not None:
                if old["instance_id"] != value["instance_id"]:
                    raise ValueError("deletion_ledger_store_mismatch")
                if old["deletion_epoch"] > value["deletion_epoch"]:
                    return "ahead"
                if not _rows(old).issubset(_rows(value)):
                    raise ValueError("deletion_ledger_history_conflict")
                if old["deletion_epoch"] == value["deletion_epoch"]:
                    if _rows(old) != _rows(value):
                        raise ValueError("deletion_ledger_history_conflict")
                    return "current"
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=root)
            try:
                with os.fdopen(fd, "wb") as output:
                    output.write(payload)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, name, src_dir_fd=root, dst_dir_fd=root)
                os.fsync(root)
            finally:
                try:
                    os.unlink(temporary, dir_fd=root)
                except FileNotFoundError:
                    pass
            return "current"
        finally:
            os.close(lock)


async def sync(session) -> str:
    """Call only AFTER commit; failures cannot undo or misreport the deletion."""
    try:
        payload = await session.run_sync(lambda db: export_sync(db.connection()))
        return await asyncio.to_thread(persist, directory(session), payload)
    except (OSError, ValueError, SQLAlchemyError):
        logger.warning("Independent deletion record could not be refreshed")
        return "unavailable"


async def status(session) -> dict:
    try:
        current = decode(await session.run_sync(lambda db: export_sync(db.connection())))
        saved = await asyncio.to_thread(read, directory(session), current["instance_id"])
        if saved is None:
            state = "missing"
        elif saved["deletion_epoch"] > current["deletion_epoch"]:
            state = "ahead"
        elif saved["deletion_epoch"] < current["deletion_epoch"]:
            state = "stale"
        else:
            state = "current" if _rows(saved) == _rows(current) else "unavailable"
        return {"status": state, "database_epoch": current["deletion_epoch"],
                "saved_epoch": saved["deletion_epoch"] if saved else None}
    except (OSError, ValueError, SQLAlchemyError):
        return {"status": "unavailable", "database_epoch": None, "saved_epoch": None}
