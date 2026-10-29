"""Run-owned durable files, exported through a bounded no-symlink boundary.

Only trusted execution context assigns ownership. Generated paths are untrusted;
never copy a link or follow a symlink parent out of the temporary workspace.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import stat
import threading
import time
import uuid
from pathlib import Path

MAX_FILES = 32
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024

_stamp_lock = threading.Lock()
_last_stamp = 0


def _stamp() -> int:
    """v0.1.64 BR2: a strictly increasing storage stamp for this process. `time.time_ns()` alone
    repeats on macOS (microsecond steps: many writes in one microsecond tie, and a tie falls back to
    the random filename) and steps back when the wall clock does (NTP, the user changing the time)."""
    global _last_stamp
    with _stamp_lock:
        _last_stamp = max(time.time_ns(), _last_stamp + 1)
        return _last_stamp


def _default_key(title: str) -> str:
    """The key of a file with no path identity (a run's exported outputs, a read-back)."""
    return hashlib.sha256(("generated:" + title).encode()).hexdigest()


def root() -> Path:
    from server import config
    return config.data_dir() / "artifacts"


def safe_filename(run_id: int, filename: str) -> bool:
    return (run_id > 0 and filename.startswith(f"run_{run_id}_")
            and len(filename) <= 220 and not any(c in filename for c in ("/", "\\", "..", "\x00"))
            and not filename.endswith(".manifest.json"))


def store_bytes(run_id: int, title: str, data: bytes, *, logical_key: str | None = None) -> dict:
    if run_id <= 0 or len(data) > MAX_FILE_BYTES:
        raise ValueError("invalid artifact owner or oversized file")
    if logical_key is not None and (not isinstance(logical_key, str) or re.fullmatch(r"[a-f0-9]{64}", logical_key) is None):
        raise ValueError("invalid artifact logical identity")
    from arslan.execution_budget import current
    budget = current()
    if budget is not None:
        budget.reserve_artifact(len(data))
    basename = re.sub(r"[^\w.() -]", "_", Path(title).name)[:120].strip(". ") or "file.bin"
    basename = basename.replace("..", "_")
    filename = f"run_{run_id}_{uuid.uuid4().hex[:16]}_{basename}"
    directory = root()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    metadata = {
        "id": f"artifact:{filename}",
        "kind": "file", "run_id": run_id, "filename": filename, "title": title[:240],
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        # From the stored (cut) title, so final_versions recognises the default key on read-back.
        "logical_key": logical_key or _default_key(title[:240]),
        "media_type": mimetypes.guess_type(basename)[0] or "application/octet-stream",
        "url": f"/api/v1/runs/{run_id}/artifacts/{filename}",
        # v0.1.64 BR2: storage order. Filenames carry a random id, so they do not sort by time.
        "stored_at_ns": _stamp(),
    }
    # UUID + exclusive create: never overwrite another deliverable or a planted link.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    manifest = path.with_name(filename + ".manifest.json")
    try:
        fd = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(metadata, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return metadata


def export_workspace(run_id: int, workspace: Path, *, excluded: set[str]) -> tuple[list[dict], list[str]]:
    """Snapshot regular outputs before cleanup, bounded by count and total bytes."""
    artifacts: list[dict] = []
    warnings: list[str] = []
    total = 0
    workspace = workspace.resolve()
    for scanned, path in enumerate(workspace.rglob("*")):
        if scanned >= 512:
            warnings.append("Output scan limit reached (512 entries)")
            break
        relative = path.relative_to(workspace)
        if any(part in excluded for part in relative.parts):
            continue
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != workspace):
            warnings.append(f"Skipped symbolic link: {relative}")
            continue
        if not path.is_file():
            continue
        if len(artifacts) >= MAX_FILES:
            warnings.append(f"Output limit reached ({MAX_FILES} files)")
            break
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    continue
                limit = min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - total)
                if info.st_size > limit:
                    warnings.append(f"Skipped oversized output: {relative}")
                    continue
                data = stream.read(limit + 1)
                if len(data) > limit:
                    warnings.append(f"Output grew beyond limit: {relative}")
                    continue
            from arslan.execution_budget import BudgetExceeded
            try:
                artifacts.append(store_bytes(run_id, str(relative), data))
            except BudgetExceeded as exc:
                warnings.append(str(exc))
                break
            total += len(data)
        except OSError as exc:
            warnings.append(f"Could not preserve {relative}: {type(exc).__name__}")
    return artifacts, warnings


def _stored_at(item: dict, manifest: Path) -> int:
    """When a manifest was written: its own `stored_at_ns`, or the manifest file's time for one
    written before v0.1.64 (BR2)."""
    value = item.get("stored_at_ns")
    if type(value) is int:
        return value
    try:
        return manifest.stat().st_mtime_ns
    except OSError:
        return 0


def _in_order(found: list[tuple[int, str, dict]]) -> list[dict]:
    return [item for _, _, item in sorted(found, key=lambda entry: (entry[0], entry[1]))]


def list_artifacts(run_id: int) -> list[dict]:
    """Every file the run stored, in the order it stored them (all versions)."""
    found = []
    for path in root().glob(f"run_{run_id}_*.manifest.json"):
        if path.is_symlink():
            continue
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            filename = item.get("filename", "")
            if item.get("run_id") == run_id and safe_filename(run_id, filename):
                target = root() / filename
                if not target.is_symlink() and target.is_file():
                    found.append((_stored_at(item, path), filename, item))
        except (OSError, ValueError, TypeError):
            continue
    return _in_order(found)


def final_versions(items: list[dict]) -> list[dict]:
    """v0.1.64 BR2 / M3 #12: one entry per file, its last version, from a list in storage order.
    `write_file` / `edit_file` store a snapshot on every write and `attach_file` stores the file
    again; all of them carry the same `logical_key` for the same path, so the run offers that path
    once, as it was last stored. An entry without a path identity stands alone: no key, or the
    default title key (`_default_key`: a run's exported outputs, where two different files can
    share a name). Order: when each final version was stored."""
    last: dict[str, int] = {}
    for index, item in enumerate(items):
        key = item.get("logical_key")
        if not key or key == _default_key(str(item.get("title", ""))):
            key = f"#{index}"
        last[key] = index
    keep = set(last.values())
    return [item for index, item in enumerate(items) if index in keep]


def artifacts_by_run(run_ids: list[int] | None, *, per_run: int | None = 20) -> dict[int, list[dict]]:
    """0.1.58 §2: the files several runs produced, in ONE pass over the folder (history rows
    carry each reply's files, so a reloaded reply shows its file cards). One card per file:
    each run's final versions (BR2), the latest `per_run` of them. `run_ids=None` is every run and
    `per_run=None` no cap (the phone's per-conversation file counts); `per_run=0` is none."""
    wanted = None if run_ids is None else {i for i in run_ids if isinstance(i, int) and i > 0}
    found: dict[int, list[tuple[int, str, dict]]] = {}
    if wanted is not None and not wanted or not root().is_dir():
        return {}
    for path in root().glob("run_*.manifest.json"):
        m = re.match(r"run_(\d+)_", path.name)
        if not m or (wanted is not None and int(m[1]) not in wanted) or path.is_symlink():
            continue
        run_id = int(m[1])
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            filename = item.get("filename", "")
            target = root() / filename
            if item.get("run_id") == run_id and safe_filename(run_id, filename) and not target.is_symlink() and target.is_file():
                found.setdefault(run_id, []).append((_stored_at(item, path), filename, item))
        except (OSError, ValueError, TypeError):
            continue
    # The latest `per_run`: a long turn's last files are the ones its reply is about.
    def cap(items: list[dict]) -> list[dict]:
        return items if per_run is None else items[len(items) - per_run:] if per_run > 0 else []
    return {run_id: cap(final_versions(_in_order(entries))) for run_id, entries in found.items()}


def read_owned(run_id: int, filename: str) -> tuple[dict, bytes]:
    """Read a bounded manifest/file pair through one no-follow directory handle.

    The caller must establish Run ownership; a filename alone is not authority.
    Metadata is cross-checked against actual bytes, not accepted as a verdict.
    """
    if not safe_filename(run_id, filename):
        raise ValueError("artifact_reference_invalid")
    directory = os.open(root(), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        def read(name, limit):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                    raise ValueError("artifact_not_regular_or_too_large")
                value = stream.read(limit + 1)
                if len(value) > limit:
                    raise ValueError("artifact_too_large")
                return value
        metadata = json.loads(read(filename + ".manifest.json", 16_384))
        if (not isinstance(metadata, dict) or type(metadata.get("run_id")) is not int or metadata.get("run_id") != run_id
                or metadata.get("filename") != filename):
            raise ValueError("artifact_manifest_mismatch")
        if (type(metadata.get("bytes")) is not int or not isinstance(metadata.get("sha256"), str)
                or re.fullmatch(r"[a-f0-9]{64}", metadata["sha256"]) is None
                or not isinstance(metadata.get("title"), str) or len(metadata["title"]) > 240
                or metadata.get("id", f"artifact:{filename}") != f"artifact:{filename}"
                or metadata.get("url") != f"/api/v1/runs/{run_id}/artifacts/{filename}"):
            raise ValueError("artifact_manifest_invalid")
        logical = metadata.get("logical_key")
        if logical is not None and (not isinstance(logical, str) or re.fullmatch(r"[a-f0-9]{64}", logical) is None):
            raise ValueError("artifact_manifest_invalid")
        data = read(filename, MAX_FILE_BYTES)
        if metadata.get("bytes") != len(data) or metadata.get("sha256") != hashlib.sha256(data).hexdigest():
            raise ValueError("artifact_integrity_mismatch")
        return metadata, data
    finally:
        os.close(directory)
