"""Internal stopped-profile switch/rollback substrate; not a user-facing entry.

A pending record blocks normal boot until rollback or explicit health-checked
finalization. Keep all older/uncooperative writers stopped and parents trusted.
Directory identities, not a possibly stale phase string, determine crash recovery.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import json
import hashlib
import os
import re
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


def prepare_from_archive(active: Path, archive: Path, candidate: Path) -> dict:
    """Read a host-selected archive; stage only to a new sibling, never activate.

    An uncertain result can leave the new candidate in place. Do not retry over
    it or infer that no staging occurred. Parent directories remain trusted.
    """
    from server.services import backup

    if (not all(path.is_absolute() and ".." not in path.parts for path in (active, archive, candidate))
            or candidate.parent != active.parent or candidate == active or _identity(active) is None):
        raise ValueError("activation_path_unsafe")
    fd = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_size > backup.MAX_TOTAL
                or before.st_size == 0):
            raise ValueError("activation_archive_unsafe")
        # The descriptor pins the selected file across renames, and NOFOLLOW /
        # NONBLOCK reject links/devices/FIFOs before ZipFile can block or parse.
        result = backup.restore(handle, candidate, current_db_path=active / "arslan.db")
        after = os.fstat(handle.fileno())
        fields = ("st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, key) != getattr(after, key) for key in fields):
            raise ValueError("activation_archive_changed")
    return {"prepared": True, "candidate": candidate.name, "files": result["files"], "secret_included": False}


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


def _read_private_json(path):
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
        return json.loads(handle.read(4097), object_pairs_hook=unique)


def _read_record(path, active):
    value = _read_private_json(path)
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


def pending_operation(active: Path) -> dict:
    """Inspect a validated journal under its lifecycle lock; never move profiles."""
    active = active.absolute()
    with hold_lifecycle(active / "arslan.db"):
        record = activation_record_path(active / "arslan.db")
        if not record.exists() and not record.is_symlink():
            return {"operation_id": None}
        value = _read_record(record, active)
        candidate, previous = (active.parent / value[key] for key in ("candidate", "previous"))
        original, replacement = value["original_identity"], value["candidate_identity"]
        if [_identity(path) for path in (active, candidate, previous)] not in (
                [original, replacement, None], [None, replacement, original], [replacement, None, original]):
            raise ValueError("activation_paths_changed")
        return {"operation_id": value["id"]}


def rollback(active: Path, operation_id: str | None = None) -> dict:
    """Restore the original directory without deleting either profile; retryable."""
    active = active.absolute()
    database = active / "arslan.db"
    with hold_lifecycle(database):
        record = activation_record_path(database)
        if not record.exists() and not record.is_symlink():
            return {"rolled_back": False}
        value = _read_record(record, active)
        if operation_id is not None and operation_id != value["id"]:
            raise ValueError("activation_operation_mismatch")
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


@contextmanager
def trial_ownership(active: Path, operation_id: str, secret: str | None):
    """Internal lease for a future trusted, restricted trial process.

    The operation ID binds a caller to an existing journal; it is NOT a user
    approval or a security credential. No generic ignore-journal switch exists.
    Normal boot, rollback and another trial remain excluded for the whole lease.
    This does not enable normal server routes or background work.
    """
    active = active.absolute()
    database = active / "arslan.db"
    with hold_lifecycle(database):
        value = _read_record(activation_record_path(database), active)
        if not isinstance(operation_id, str) or operation_id != value["id"]:
            raise ValueError("activation_operation_mismatch")
        candidate, previous = (active.parent / value[key] for key in ("candidate", "previous"))
        if [_identity(path) for path in (active, candidate, previous)] != [
                value["candidate_identity"], None, value["original_identity"]]:
            raise ValueError("activation_paths_changed")
        with _hold_file(active / ".arslan.db.arslan-lock"):
            # Recheck the actual trial secret, not merely the earlier switch's
            # preflight result. A launcher may have inherited a different key.
            result = check(database, secret)
            if result["status"] not in ("compatible", "no_stored_credentials"):
                raise ValueError("activation_credentials_refused")
            yield {"operation_id": value["id"], "status": "trial_owned"}


def _operation_path(active, operation_id, suffix):
    if not isinstance(operation_id, str) or str(UUID(operation_id)) != operation_id:
        raise ValueError("activation_operation_mismatch")
    record = activation_record_path(active / "arslan.db")
    return record.with_name(f"{record.name}.{operation_id}.{suffix}")


def _database_digest(database):
    fd = os.open(database, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1
                or before.st_size > 512 * 1024 * 1024):
            raise ValueError("activation_database_unsafe")
        digest = hashlib.sha256()
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
        after = os.fstat(handle.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("activation_database_changed")
    return digest.hexdigest()


def _validate_receipt(value, operation_id):
    if (not isinstance(value, dict)
            or set(value) != {"format", "operation_id", "candidate_identity", "database_sha256"}
            or type(value["format"]) is not int or value["format"] != 1
            or value["operation_id"] != operation_id):
        raise ValueError("activation_receipt_invalid")
    identity = value["candidate_identity"]
    if (not isinstance(identity, list) or len(identity) != 2
            or any(type(part) is not int or part < 0 for part in identity)
            or not isinstance(value["database_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["database_sha256"])):
        raise ValueError("activation_receipt_invalid")
    return value


def invalidate_trial_receipt_locked(active, operation_id):
    """Trial lifecycle only, while holding trial_ownership; no stale success reuse."""
    path = _operation_path(active, operation_id, "ready")
    if path.exists() or path.is_symlink():
        _validate_receipt(_read_private_json(path), operation_id)
        path.unlink()
        _sync_parent(path.parent)


def record_trial_success_locked(active, operation_id, secret):
    """After observed health and graceful engine disposal, still under trial lock."""
    value = _read_record(activation_record_path(active / "arslan.db"), active)
    if value["id"] != operation_id or _identity(active) != value["candidate_identity"]:
        raise ValueError("activation_paths_changed")
    if check(active / "arslan.db", secret)["status"] not in ("compatible", "no_stored_credentials"):
        raise ValueError("activation_credentials_refused")
    receipt = {"format": 1, "operation_id": operation_id, "candidate_identity": value["candidate_identity"],
               "database_sha256": _database_digest(active / "arslan.db")}
    # Exclusive creation: a duplicate receipt is not silently replaced.
    _write_record(_operation_path(active, operation_id, "ready"), receipt)


def _check_latest_deletions(active, previous):
    import sqlite3
    from sqlalchemy import create_engine
    from server.services.memory_deletion_ledger import select_for_restore, _rows
    from server.services.memory_deletion_manifest import decode, export_sync

    current = decode(select_for_restore(previous / "arslan.db")[0])
    uri = (active / "arslan.db").as_uri() + "?mode=ro&immutable=1"
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
    try:
        with engine.connect() as connection:
            candidate = decode(export_sync(connection))
    finally:
        engine.dispose()
    if (candidate["instance_id"] != current["instance_id"]
            or candidate["deletion_epoch"] < current["deletion_epoch"]
            or not _rows(current).issubset(_rows(candidate))):
        raise ValueError("activation_deletion_records_advanced")


def finalize(active: Path, operation_id: str, secret: str | None) -> dict:
    """Trusted coordinator only, AFTER user approval, health response and child exit.

    A receipt proves local trial completion, not user approval or model quality.
    Keep the original profile and completed journal; never delete user data.
    """
    active = active.absolute()
    record = activation_record_path(active / "arslan.db")
    completed = _operation_path(active, operation_id, "completed")
    with hold_lifecycle(active / "arslan.db"):
        if not record.exists() and not record.is_symlink():
            value = _read_record(completed, active)
            candidate, previous = (active.parent / value[key] for key in ("candidate", "previous"))
            if (value["id"] != operation_id or [_identity(path) for path in (active, candidate, previous)] !=
                    [value["candidate_identity"], None, value["original_identity"]]):
                raise ValueError("activation_paths_changed")
            return {"finalized": True, "already_finalized": True, "original_retained": True}
        value = _read_record(record, active)
        candidate, previous = (active.parent / value[key] for key in ("candidate", "previous"))
        if (value["id"] != operation_id or [_identity(path) for path in (active, candidate, previous)] !=
                [value["candidate_identity"], None, value["original_identity"]]):
            raise ValueError("activation_paths_changed")
        with _hold_file(active / ".arslan.db.arslan-lock"), _hold_file(previous / ".arslan.db.arslan-lock"):
            receipt = _validate_receipt(_read_private_json(_operation_path(active, operation_id, "ready")), operation_id)
            if (receipt["candidate_identity"] != value["candidate_identity"]
                    or receipt["database_sha256"] != _database_digest(active / "arslan.db")):
                raise ValueError("activation_health_stale")
            if check(active / "arslan.db", secret)["status"] not in ("compatible", "no_stored_credentials"):
                raise ValueError("activation_credentials_refused")
            _check_latest_deletions(active, previous)
            _move(record, completed)  # Atomically remove the normal-boot block, retaining metadata.
    return {"finalized": True, "already_finalized": False, "original_retained": True}
