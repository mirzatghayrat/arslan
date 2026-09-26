"""Stopped/startup profile backup, before any schema write; no secret access."""
from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4
import hashlib

from server.services import backup

ERROR = "database_upgrade_backup_failed"
_prepared: dict[tuple, tuple[Path, str]] = {}


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def check_space(database: Path) -> None:
    size = database.stat().st_size
    for name in backup.ASSET_DIRS:
        root = database.parent / name
        if root.is_symlink():
            raise ValueError("unsafe assets")
        if root.exists():
            for path in root.rglob("*"):
                if path.is_symlink():
                    raise ValueError("unsafe asset")
                if path.is_file():
                    size += path.stat().st_size
    wal = database.with_name(database.name + "-wal")
    if wal.exists():
        size += wal.stat().st_size
    required = size * 3 + 64 * 1024 * 1024
    if any(shutil.disk_usage(p).free < required for p in (database.parent, tempfile.gettempdir())):
        raise OSError("insufficient backup space")


def create(database: Path, previous: str, target: str) -> Path:
    try:
        data = database.parent
        fingerprint = tuple(digest(p) if p.exists() else None
                            for p in (database, database.with_name(database.name + "-wal")))
        identity = (str(database.resolve()), previous, target, fingerprint)
        cached = _prepared.get(identity)
        if cached is not None and cached[0].is_file():
            if cached[0].is_symlink() or digest(cached[0]) != cached[1]:
                raise ValueError("backup changed before migration")
            return cached[0]
        directory = data / "backups"
        if directory.is_symlink():
            raise ValueError("unsafe backup directory")
        check_space(database)
        directory.mkdir(mode=0o700, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = directory / f"upgrade-from-schema-{previous}-to-0.1.40-schema-{target}-{timestamp}-{uuid4().hex[:8]}.zip"
        backup.create(data, destination, db_path=database)
        # Only our automatic upgrade archives; never delete manual/user backups.
        archives = sorted((p for p in directory.glob("upgrade-from-schema-*-to-*-schema-*.zip")
                           if p.is_file() and not p.is_symlink()), key=lambda p: p.name)
        archives.sort(key=lambda p: p.stat().st_mtime_ns)
        for old in archives[:-3]:
            old.unlink()
        _prepared[identity] = (destination, digest(destination))
        return destination
    except Exception:
        raise RuntimeError(ERROR) from None
