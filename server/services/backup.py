"""Portable, checksummed backups. Restore ONLY into a new directory, never live data.

The database snapshot includes its PBKDF2 salt, but NOT the external encryption
secret or access tokens. Stop the app before backup for a consistent file/DB pair.
SQLite's backup API additionally handles committed WAL content correctly.
"""
from __future__ import annotations

import hashlib
from contextlib import closing, nullcontext
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from typing import BinaryIO

FORMAT = 1
MAX_FILE = 512 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024
MAX_FILES = 10_000
ASSET_DIRS = ("artifacts", "spawns", "skill_scripts", "uploads")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_db(path: Path) -> None:
    # Only our closed, standalone snapshot/staging DBs reach this helper.
    # A read-only WAL connection can itself leave WAL/SHM files behind. Avoid
    # creating them, but never ignore an already present pending journal.
    for suffix in ("-wal", "-shm", "-journal"):
        journal = path.with_name(path.name + suffix)
        if journal.exists() or journal.is_symlink():
            raise ValueError("backup database has pending journals")
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("database integrity check failed")


def _restore_language_hint(staged: Path) -> None:
    """Derive display-only metadata in our private, not-yet-installed stage.

    Never copy an archive hint or import config/key bootstrap. Missing/legacy
    language settings fall back to English; no other setting is materialized.
    The stage is owned by this restore call and cannot contain this root member
    from the archive. An output failure aborts before candidate installation.
    """
    from server.locale_codes import normalize

    language = "en"
    try:
        with closing(sqlite3.connect(f"{(staged / 'arslan.db').as_uri()}?mode=ro&immutable=1", uri=True)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA query_only=ON")
            remaining = 100

            def bounded_query():
                nonlocal remaining
                remaining -= 1
                return remaining <= 0

            db.set_progress_handler(bounded_query, 1000)
            if db.execute("SELECT type FROM sqlite_master WHERE name='settings'").fetchone() == ("table",):
                rows = db.execute("SELECT substr(value,1,65),length(value),typeof(value) "
                                  "FROM settings WHERE key='language' LIMIT 2").fetchall()
                if len(rows) == 1 and rows[0][2] == "text" and rows[0][1] <= 64:
                    language = normalize(rows[0][0])
    except sqlite3.Error:
        # This cache is not schema validation or permission to activate a DB.
        # Existing restore/preflight/trial checks remain independently required.
        pass
    with (staged / "ui_language").open("xb") as output:
        os.chmod(staged / "ui_language", 0o600)
        output.write((language + "\n").encode("ascii"))
        output.flush()
        os.fsync(output.fileno())


def create(data_dir: Path, destination: Path, *, db_path: Path | None = None,
           spawns_dir: Path | None = None) -> dict:
    """Caller must stop the app; archive contains private data but not the key."""
    data_dir, destination = data_dir.resolve(), destination.absolute()
    source_db = (db_path or data_dir / "arslan.db").resolve()
    if not source_db.is_file():
        raise ValueError("database does not exist")
    if destination.exists():
        raise ValueError("backup destination already exists")
    manifest = {"format": FORMAT, "files": {}, "secret_included": False,
                "restore_requires": "original ARSLAN_SECRET_KEY; app stopped",
                "excluded": ["sandbox_env", "shell_workspace", "shell_ca", "access tokens", "external secret"]}
    total = 0
    with tempfile.TemporaryDirectory(prefix="arslan-backup-") as tmp:
        snapshot = Path(tmp) / "arslan.db"
        with closing(sqlite3.connect(f"{source_db.as_uri()}?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(snapshot)) as dst:
                src.backup(dst)
        _check_db(snapshot)
        archive = Path(tmp) / "backup.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
            def add(name: str, path: Path):
                nonlocal total
                fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                with os.fdopen(fd, "rb") as handle:
                    info = os.fstat(handle.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
                        raise ValueError("backup contains non-regular or oversized file")
                    data = handle.read(MAX_FILE + 1)
                total += len(data)
                if len(data) > MAX_FILE or total > MAX_TOTAL or len(manifest["files"]) >= MAX_FILES:
                    raise ValueError("backup size/count limit exceeded")
                z.writestr(name, data)
                manifest["files"][name] = {"bytes": len(data), "sha256": _digest(data)}

            add("arslan.db", snapshot)
            for directory in ASSET_DIRS:
                root = Path(spawns_dir) if directory == "spawns" and spawns_dir else data_dir / directory
                if root.is_symlink():
                    raise ValueError("backup asset directory is a symlink")
                if not root.exists():
                    continue
                root = root.resolve()
                for path in root.rglob("*"):
                    if path.is_symlink():
                        raise ValueError("backup refuses symlink assets")
                    if path.is_file():
                        add(f"{directory}/{path.relative_to(root).as_posix()}", path)
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True))
        # Exclusive create: never replace a previous backup even after a race.
        with destination.open("xb") as output, archive.open("rb") as source:
            os.chmod(destination, 0o600)
            shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())
    return {"files": len(manifest["files"]), "bytes": total, "secret_included": False}


def restore(archive: Path | BinaryIO, destination: Path, *, deletion_manifest: bytes | None = None,
            current_db_path: Path | None = None) -> dict:
    """App stopped: reconcile trusted current records, install only to a new path."""
    from server.services.data_profile_lock import hold

    # A trusted current installation path is supplied by the maintenance caller.
    # Never terminate the owner or wait until a stale approval becomes usable.
    with hold(current_db_path) if current_db_path is not None else nullcontext():
        return _restore_stopped(archive, destination, deletion_manifest=deletion_manifest,
                                current_db_path=current_db_path)


def _restore_stopped(archive: Path | BinaryIO, destination: Path, *, deletion_manifest: bytes | None,
                     current_db_path: Path | None) -> dict:
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("restore requires a NEW directory; existing data is never overwritten")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".arslan-restore-", dir=destination.parent) as tmp:
        staged = Path(tmp) / "data"
        staged.mkdir(mode=0o700)
        with zipfile.ZipFile(archive) as z:
            infos = z.infolist()
            names = [i.filename for i in infos]
            if len(names) != len(set(names)) or len(names) > MAX_FILES + 1:
                raise ValueError("duplicate archive paths or too many files")
            if "manifest.json" not in names or z.getinfo("manifest.json").file_size > 4 * 1024 * 1024:
                raise ValueError("missing/oversized backup manifest")
            manifest = json.loads(z.read("manifest.json"))
            expected = manifest.get("files", {})
            if manifest.get("format") != FORMAT or set(names) != set(expected) | {"manifest.json"}:
                raise ValueError("unsupported or inconsistent backup manifest")
            if "arslan.db" not in expected or sum(i.file_size for i in infos) > MAX_TOTAL:
                raise ValueError("missing database or oversized archive")
            for info in infos:
                if info.filename == "manifest.json":
                    continue
                path = PurePosixPath(info.filename)
                if (path.is_absolute() or ".." in path.parts or "\\" in info.filename
                        or not path.parts or path.parts[0] not in (*ASSET_DIRS, "arslan.db")
                        or stat.S_ISLNK(info.external_attr >> 16) or info.is_dir()
                        or info.file_size > MAX_FILE):
                    raise ValueError("unsafe backup member")
                data = z.read(info)
                if expected[info.filename] != {"bytes": len(data), "sha256": _digest(data)}:
                    raise ValueError("backup checksum mismatch")
                target = staged.joinpath(*path.parts)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with target.open("xb") as handle:
                    os.chmod(target, 0o600)
                    handle.write(data)
        _check_db(staged / "arslan.db")
        from sqlalchemy import create_engine
        from server.services.memory_restore import mark_restored_sync
        engine = create_engine(f"sqlite:///{staged / 'arslan.db'}")
        try:
            with engine.begin() as connection:
                review = mark_restored_sync(connection)
                reconciliation = {"applied": False, "reason": "no_deletion_manifest"}
                selection = {"selected_source": "imported_manifest" if deletion_manifest is not None else "none"}
                if current_db_path is not None:
                    from server.services.memory_deletion_ledger import select_for_restore
                    deletion_manifest, selection = select_for_restore(current_db_path, deletion_manifest)
                if deletion_manifest is not None:
                    from server.services.memory_deletion_manifest import reconcile_staged_sync
                    reconciliation = reconcile_staged_sync(connection, deletion_manifest)
        finally:
            engine.dispose()
        _check_db(staged / "arslan.db")
        # Destination must remain absent. Never merge into or replace live data.
        _restore_language_hint(staged)
        if destination.exists() or destination.is_symlink():
            raise ValueError("restore destination appeared during validation")
        from server.services.atomic_install import install_directory
        install_directory(staged, destination)
    return {"files": len(expected), "secret_included": False,
            "memory_review": review,
            "deletion_reconciliation": reconciliation,
            "deletion_record_selection": selection,
            "next_step": "Keep the app stopped; configure the original secret and restored data path before boot. "
                         "Review restored memories, projects and paused schedules before using them."}
