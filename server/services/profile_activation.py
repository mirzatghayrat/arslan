"""Internal stopped-profile switch/rollback substrate; not a user-facing entry.

No finalize/trial-boot path is enabled yet. A pending record blocks normal boot
until rollback. Keep all older/uncooperative writers stopped and parents trusted.
Directory identities, not a possibly stale phase string, determine crash recovery.
"""
from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import stat
from uuid import UUID, uuid4

from server.services.atomic_install import install_directory
from server.services.data_profile_lock import (activation_record_path, hold, hold_lifecycle, _hold_file)
from server.services.recovery_preflight import check


def _identity(path: Path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("activation_path_unsafe")
    return [info.st_dev, info.st_ino]


def _sync_parent(parent):
    fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _move(source, destination):
    install_directory(source, destination)
    _sync_parent(source.parent)


def _write_record(path, value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    _sync_parent(path.parent)


def _read_record(path, active):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                or info.st_mode & 0o077 or info.st_size > 4096):
            raise ValueError("activation_record_unsafe")
        def unique(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError("activation_record_invalid")
                result[key] = item
            return result
        value = json.loads(handle.read(4097), object_pairs_hook=unique)
    keys = {"format", "id", "active", "candidate", "previous", "original_identity", "candidate_identity"}
    if (not isinstance(value, dict) or set(value) != keys or type(value["format"]) is not int
            or value["format"] != 1 or value["active"] != active.name):
        raise ValueError("activation_record_invalid")
    try:
        if str(UUID(value["id"])) != value["id"]:
            raise ValueError
        for key in ("active", "candidate", "previous"):
            name = value[key]
            if not isinstance(name, str) or not name or name in (".", "..") or Path(name).name != name:
                raise ValueError
        if len({value[key] for key in ("active", "candidate", "previous")}) != 3:
            raise ValueError
        if value["previous"] != f".arslan-previous-{value['id']}":
            raise ValueError
        for key in ("original_identity", "candidate_identity"):
            identity = value[key]
            if (not isinstance(identity, list) or len(identity) != 2
                    or any(type(part) is not int or part < 0 for part in identity)):
                raise ValueError
        if value["original_identity"] == value["candidate_identity"]:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("activation_record_invalid") from error
    return value


def switch_for_trial(active: Path, candidate: Path, secret: str | None) -> dict:
    """Internal only: validate/reconcile, journal, switch; leave normal boot blocked.

    The future native coordinator must add authenticated trial boot and health
    verification before this can become a user-facing activation workflow.
    """
    active, candidate = active.absolute(), candidate.absolute()
    original_id, candidate_id = _identity(active), _identity(candidate)
    if (original_id is None or candidate_id is None or active.parent != candidate.parent
            or original_id == candidate_id or original_id[0] != candidate_id[0]):
        raise ValueError("activation_paths_invalid")
    database = active / "arslan.db"
    restored_db = candidate / "arslan.db"
    with hold(database), hold(restored_db):
        if _identity(active) != original_id or _identity(candidate) != candidate_id:
            raise ValueError("activation_paths_changed")
        preflight = check(restored_db, secret)
        if preflight["status"] not in ("compatible", "no_stored_credentials"):
            raise ValueError("activation_credentials_refused")
        # Reconcile again: deletion records may have advanced since restoration.
        from server.services.memory_deletion_ledger import select_for_restore
        from server.services.memory_deletion_manifest import reconcile_staged_sync
        from sqlalchemy import create_engine
        payload, _ = select_for_restore(database)
        engine = create_engine(f"sqlite:///{restored_db}")
        try:
            with engine.begin() as connection:
                reconcile_staged_sync(connection, payload)
        finally:
            engine.dispose()
        operation = str(uuid4())
        previous = active.parent / f".arslan-previous-{operation}"
        value = {"format": 1, "id": operation, "active": active.name, "candidate": candidate.name,
                 "previous": previous.name, "original_identity": original_id, "candidate_identity": candidate_id}
        record = activation_record_path(database)
        _write_record(record, value)  # Must be durable before either rename.
        _move(active, previous)
        _move(candidate, active)
    return {"status": "trial_pending", "operation_id": operation}


def rollback(active: Path) -> dict:
    """Restore the original directory without deleting either profile; retryable."""
    active = active.absolute()
    database = active / "arslan.db"
    with hold_lifecycle(database):
        record = activation_record_path(database)
        if not record.exists() and not record.is_symlink():
            return {"rolled_back": False}
        value = _read_record(record, active)
        candidate, previous = (active.parent / value[key] for key in ("candidate", "previous"))
        with ExitStack() as stack:
            identities = [_identity(path) for path in (active, candidate, previous)]
            original, replacement = value["original_identity"], value["candidate_identity"]
            allowed = ([original, replacement, None], [None, replacement, original],
                       [replacement, None, original])
            if identities not in allowed:
                raise ValueError("activation_paths_changed")
            for path, identity in zip((active, candidate, previous), identities):
                if identity is not None:
                    stack.enter_context(_hold_file(path / ".arslan.db.arslan-lock"))
            if identities == [replacement, None, original]:
                _move(active, candidate)
            if _identity(active) is None:
                _move(previous, active)
            if [_identity(path) for path in (active, candidate, previous)] != [original, replacement, None]:
                raise ValueError("activation_paths_changed")
            record.unlink()
            _sync_parent(record.parent)
    return {"rolled_back": True}
