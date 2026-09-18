"""Private deletion snapshots independent of the SQLite/backup snapshot.

Post-commit mirror, not a second writable memory store or a disaster backup.
Boot repairs the commit-to-file crash window. Restore must explicitly reconcile
the latest ledger before installation; copying a DB by hand bypasses that flow.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import logging
import json
import os
from pathlib import Path
import sqlite3
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


def select_for_restore(current_db_path: Path, imported: bytes | None = None) -> tuple[bytes, dict]:
    """Read a stopped installation; never modify its DB, ledger or imports.

    Read-only DB export closes the post-commit mirror gap. A newer independent
    ledger wins over an older DB, but divergent histories fail closed. The
    caller must still match the selected store to the staged backup.
    """
    from sqlalchemy import create_engine

    database = current_db_path.absolute()
    if database.is_symlink() or not database.is_file():
        raise ValueError("deletion_current_database_unavailable")
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True))
    try:
        with engine.connect() as connection:
            # Explicit BEGIN gives both export SELECTs one SQLite snapshot,
            # including under the sqlite3 legacy transaction-control default.
            connection.exec_driver_sql("BEGIN")
            current = decode(export_sync(connection))
    except (OSError, ValueError, SQLAlchemyError, sqlite3.Error) as exc:
        raise ValueError("deletion_current_database_unavailable") from exc
    finally:
        engine.dispose()
    saved = read(database.parent / DIRECTORY, current["instance_id"])
    candidates = [("current_database", current)]
    if saved is not None:
        candidates.append(("local_ledger", saved))
    if imported is not None:
        candidates.append(("imported_manifest", decode(imported)))
    if any(value["instance_id"] != current["instance_id"] for _, value in candidates):
        raise ValueError("deletion_manifest_store_mismatch")
    selected_source, selected = max(candidates, key=lambda item: item[1]["deletion_epoch"])
    selected_rows = _rows(selected)
    for _, value in candidates:
        rows = _rows(value)
        if not rows.issubset(selected_rows) or (
                value["deletion_epoch"] == selected["deletion_epoch"] and rows != selected_rows):
            raise ValueError("deletion_ledger_history_conflict")
    payload = json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    decode(payload)  # Keep the transfer bound after canonical serialization.
    return payload, {"selected_source": selected_source,
                     "sources_checked": [source for source, _ in candidates],
                     "deletion_epoch": selected["deletion_epoch"],
                     "local_ledger_present": saved is not None}
