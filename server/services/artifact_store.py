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
import uuid
from pathlib import Path

MAX_FILES = 32
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024


def root() -> Path:
    from server import config
    return config.data_dir() / "artifacts"


def safe_filename(run_id: int, filename: str) -> bool:
    return (run_id > 0 and filename.startswith(f"run_{run_id}_")
            and len(filename) <= 220 and not any(c in filename for c in ("/", "\\", "..", "\x00"))
            and not filename.endswith(".manifest.json"))


def store_bytes(run_id: int, title: str, data: bytes) -> dict:
    if run_id <= 0 or len(data) > MAX_FILE_BYTES:
        raise ValueError("invalid artifact owner or oversized file")
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
        "kind": "file", "run_id": run_id, "filename": filename, "title": title[:240],
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "media_type": mimetypes.guess_type(basename)[0] or "application/octet-stream",
        "url": f"/api/v1/runs/{run_id}/artifacts/{filename}",
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


def list_artifacts(run_id: int) -> list[dict]:
    out = []
    for path in sorted(root().glob(f"run_{run_id}_*.manifest.json")):
        if path.is_symlink():
            continue
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            filename = item.get("filename", "")
            if item.get("run_id") == run_id and safe_filename(run_id, filename):
                target = root() / filename
                if not target.is_symlink() and target.is_file():
                    out.append(item)
        except (OSError, ValueError, TypeError):
            continue
    return out
