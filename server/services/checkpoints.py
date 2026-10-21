"""S3 (v0.1.63): a turn's file changes can be undone (card S3; ⓪Plan's answers in the S3 plan).

Before this, nothing kept the OLD contents: `file_tools._snapshot_write` stores what a run wrote, as a
deliverable. Now the first write_file, edit_file or run_command of a run (one Run, `execution_context`)
saves the working folder first, once; the earliest copy is the one an undo goes back to.

- **Where:** `<data dir>/checkpoints/<run_id>/`: a `manifest.json` and one copy per folder. The data
  folder is closed to sandboxed commands (`command_sandbox.arslan_protected`). A command the user let
  out of the sandbox can still write here, so `finish` records each copied file's sha256 and a restore
  checks it before writing back (Q3); a change made inside the same run before `finish` is not caught.
- **How:** a walk that never follows links, cloning each regular file with `clonefile(2)` on APFS (almost
  no space: the copy shares blocks until the original changes), else copying it (≤ 50 MB). Folders that
  can be rebuilt are left out and listed; so are Arslan's own paths and the user's secrets. FIFOs,
  sockets, devices and symlinks are never opened or copied, only listed (a FIFO froze the backend once).
  Every folder kept is recreated, empty ones too: a folder missing from the copy is one the run made.
- **A file write_file or edit_file writes under a left-out folder** is cloned on its own just before
  its first write in the run, and listed under `written` (the card: "the folders saved and the files
  this turn wrote"). Commands that change left-out folders are not saved there.
- **A save that fails never stops the change** (logged; that run has no undo), as `finish` never fails
  the run. A copy under the id of a run that did not save in this process is never taken for it.
- **Not saved, and said so:** more than MAX_FILES files or MAX_BYTES (counted first), too little free
  disk, or a folder on another volume than the data folder.
- **When the run ends** (`finish`, from host_run, whatever way it ended): for every path the run changed,
  how it left it (size, mtime, sha256; None when deleted) and the saved copy's sha256 (None when the run
  created it). Paths the run did not change are not hashed: a copy keeps size and mtime.
"""
from __future__ import annotations

import asyncio
import ctypes
import errno
import hashlib
import json
import logging
import os
import plistlib
import shutil
import stat
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

#: Folders that can be rebuilt, left out of the copy (the undo box says so). `.git` is kept.
EXCLUDED = frozenset({"node_modules", ".venv", "venv", "__pycache__", "build", "dist", ".next", "target",
                      "DerivedData", ".build"})
MAX_FILES = 20_000
MAX_BYTES = 5 * 1024 ** 3
MIN_FREE = 5 * 1024 ** 3
#: Without clonefile (Linux CI, a non-APFS volume) a file is copied only up to this size. DELETE-BY: when
#: CI no longer runs these tests on Linux and Arslan no longer supports non-APFS volumes (card S3).
COPY_MAX = 50 * 1024 ** 2
_CLONE_NOFOLLOW = 0x0001
_TM_EXCLUDE = b"com.apple.metadata:com_apple_backup_excludeItem"

_locks: dict[int, asyncio.Lock] = {}
#: Which runs are changing which folder, in this process: a restore waits for a folder's runs to end,
#: and runs that overlap are listed on each other's manifest.
_touching: dict[str, set[int]] = {}
#: Runs that saved in this process and have not finished. A copy on disk under the id of a run not in
#: here is an earlier run's (a database made anew gives ids out again): never taken for this run's.
_live: set[int] = set()


def root_dir() -> Path:
    from server import config
    return config.data_dir() / "checkpoints"


def _run_dir(run_id: int) -> Path:
    return root_dir() / str(int(run_id))


def manifest(run_id: int | None) -> dict | None:
    if run_id is None:
        return None
    try:
        return json.loads((_run_dir(run_id) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save(run_id: int, data: dict) -> None:
    path = _run_dir(run_id) / "manifest.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _entry(data: dict, root: Path) -> dict | None:
    return next((r for r in data["roots"] if r["path"] == str(root)), None)


def clone_of(run_id: int, root: Path) -> Path | None:
    data = manifest(run_id)
    entry = _entry(data, Path(root).resolve()) if data else None
    if entry is None or entry["skipped"] is not None:
        return None
    return _run_dir(run_id) / entry["clone"]


def _reset_for_tests() -> None:
    _locks.clear()
    _touching.clear()
    _live.clear()


def _make_root() -> None:
    root = root_dir()
    if root.exists():
        return
    root.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        # Kept out of Time Machine: these are copies of the user's own files, a week at most. The attribute
        # `tmutil addexclusion` writes, set directly: tmutil itself takes ~11 s (measured 2026-10-22).
        value = plistlib.dumps("com.apple.backupd", fmt=plistlib.FMT_BINARY)
        libc = _libc()
        libc.setxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t,
                                  ctypes.c_uint32, ctypes.c_int]
        if libc.setxattr(os.fsencode(root), _TM_EXCLUDE, value, len(value), 0, 0) != 0:
            logger.warning("checkpoints: could not exclude %s from Time Machine", root)


def _same_volume(a: Path, b: Path) -> bool:
    return os.stat(a).st_dev == os.stat(b).st_dev


def _free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def _protected() -> list[Path]:
    from server.services import command_sandbox
    return [Path(p).resolve() for p in command_sandbox.default_protected()]


def _skip_dir(path: Path, name: str, protected: list[Path]) -> bool:
    return name in EXCLUDED or any(path == p or p in path.parents for p in protected)


def _walk(root: Path, protected: list[Path], excluded: set[str], not_regular: list[str],
          folders: list[str] | None = None):
    """(relative path, absolute path, lstat) for each regular file under `root`, never following a link.
    Skipped directories go into `excluded`, everything that is not a regular file into `not_regular`,
    and every directory kept into `folders` when given."""
    for top, dirs, files in os.walk(root, followlinks=False):
        here = Path(top)
        keep = []
        for name in dirs:
            path = here / name
            if os.path.islink(path):
                not_regular.append(str(path.relative_to(root)))
            elif _skip_dir(path, name, protected):
                excluded.add(name if name in EXCLUDED else str(path.relative_to(root)))
            else:
                keep.append(name)
                if folders is not None:
                    folders.append(str(path.relative_to(root)))
        dirs[:] = keep
        for name in files:
            path = here / name
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                yield str(path.relative_to(root)), path, st
            else:
                not_regular.append(str(path.relative_to(root)))


def _libc():
    return ctypes.CDLL(None, use_errno=True)


def _clone_file(src: Path, dst: Path, size: int) -> str:
    """'clonefile' or 'copy'; raises OSError when neither can be done (too big to copy)."""
    if sys.platform == "darwin":
        libc = _libc()
        libc.clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
        if libc.clonefile(os.fsencode(src), os.fsencode(dst), _CLONE_NOFOLLOW) == 0:
            return "clonefile"
        err = ctypes.get_errno()
        if err not in (errno.ENOTSUP, errno.EXDEV, errno.EPERM):
            raise OSError(err, os.strerror(err), str(src))
    if size > COPY_MAX:
        raise OSError(errno.EFBIG, "too large to copy", str(src))
    shutil.copy2(src, dst, follow_symlinks=False)
    return "copy"


def _count(root: Path, protected: list[Path]) -> str | None:
    files = size = 0
    for _, _, st in _walk(root, protected, set(), []):
        files += 1
        size += st.st_size
        if files > MAX_FILES or size > MAX_BYTES:
            return "too_large"
    return None


def _copy_tree(root: Path, dest: Path, protected: list[Path]) -> dict:
    excluded: set[str] = set()
    not_regular: list[str] = []
    failed: list[str] = []
    folders: list[str] = []
    methods: set[str] = set()
    started = time.monotonic()
    dest.mkdir(parents=True)
    for rel, path, st in _walk(root, protected, excluded, not_regular, folders):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            methods.add(_clone_file(path, target, st.st_size))
        except OSError:
            failed.append(rel)
    for rel in folders:  # empty ones too: a folder missing from the copy is one the run made
        (dest / rel).mkdir(parents=True, exist_ok=True)
    return {"excluded": sorted(excluded), "not_regular": sorted(not_regular), "failed": sorted(failed),
            "method": "clonefile" if "clonefile" in methods else ("copy" if methods else None),
            "seconds": round(time.monotonic() - started, 3)}


def _save_root(run_id: int, root: Path, index: int) -> dict:
    entry = {"path": str(root), "clone": f"copy-{index}", "skipped": None, "excluded": [], "not_regular": [],
             "failed": [], "written": [], "method": None, "seconds": 0.0, "finished": None}
    protected = _protected()
    if not _same_volume(root, root_dir()):
        entry["skipped"] = "other_volume"
    elif _free_bytes(root_dir()) < MIN_FREE:
        entry["skipped"] = "low_disk"
    else:
        entry["skipped"] = _count(root, protected)
    if entry["skipped"] is None:
        entry.update(_copy_tree(root, _run_dir(run_id) / entry["clone"], protected))
    return entry


async def ensure(run_id: int | None, roots: list[Path], written: Path | None = None) -> None:
    """Before a run's first change in `roots`: save each folder once. No run, no save.
    `written` is the file write_file or edit_file is about to write: under a left-out folder
    (node_modules, …) it is saved on its own, before its first write in the run."""
    if run_id is None:
        return
    if written is not None:  # its folder resolved, never the file itself: it may be a link
        written = Path(written).parent.resolve() / Path(written).name
    lock = _locks.setdefault(run_id, asyncio.Lock())
    async with lock:
        try:
            await asyncio.to_thread(_ensure_sync, int(run_id), [Path(r).resolve() for r in roots], written)
        except Exception:  # noqa: BLE001 — a save that fails never stops the change; the run has no undo
            logger.warning("checkpoints: saving for run %s failed", run_id, exc_info=True)


def _ensure_sync(run_id: int, roots: list[Path], written: Path | None = None) -> None:
    _make_root()
    data = manifest(run_id) if run_id in _live else None
    if data is None:
        from server.services import personal_context
        ctx = personal_context.current()
        shutil.rmtree(_run_dir(run_id), ignore_errors=True)  # an earlier run's, if any: not this one's
        _run_dir(run_id).mkdir(parents=True, exist_ok=True)
        _live.add(run_id)
        data = {"run_id": run_id, "created_at": time.time(), "roots": [], "overlap": [],
                "conversation_id": ctx.conversation_id if ctx else None,
                # The turn's user message (its row has no run id): S3b's conversation restore starts there.
                "message_id": getattr(ctx, "source_message_id", None) if ctx else None}
    changed = False
    for root in roots:
        others = _touching.setdefault(str(root), set()) - {run_id}
        _touching[str(root)].add(run_id)
        for other in others:
            if other not in data["overlap"]:
                data["overlap"].append(other)
                changed = True
            _note_overlap(other, run_id)
        if _entry(data, root) is None:
            data["roots"].append(_save_root(run_id, root, len(data["roots"])))
            changed = True
    if written is not None and _save_written(run_id, data, written):
        changed = True
    if changed:
        _save(run_id, data)


def _save_written(run_id: int, data: dict, path: Path) -> bool:
    """A file about to be written under a left-out folder: cloned on its own, once. A new one is only listed."""
    for entry in data["roots"]:
        root = Path(entry["path"])
        if entry["skipped"] is not None or not path.is_relative_to(root):
            continue
        rel = path.relative_to(root)
        if not any(part in EXCLUDED for part in rel.parts[:-1]) or str(rel) in entry["written"]:
            return False
        entry["written"].append(str(rel))
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            return True
        if stat.S_ISREG(st.st_mode):
            target = _run_dir(run_id) / entry["clone"] / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                _clone_file(path, target, st.st_size)
            except OSError:
                entry["failed"].append(str(rel))
        return True
    return False


def _note_overlap(run_id: int, other: int) -> None:
    data = manifest(run_id)
    if data is not None and other not in data["overlap"]:
        data["overlap"].append(other)
        _save(run_id, data)


def _fingerprint(path: Path) -> dict | None:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(st.st_mode):
        return {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": None}
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": _sha256(path)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb", buffering=0) as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _finish_root(run_id: int, entry: dict) -> None:
    root = Path(entry["path"])
    clone = _run_dir(run_id) / entry["clone"]
    protected = _protected()
    saved = {rel: st for rel, _, st in _walk(clone, [], set(), [])}
    now = {rel: st for rel, _, st in _walk(root, protected, set(), [])}
    for rel in entry["written"]:  # under left-out folders, which neither walk enters
        for side, base in ((saved, clone), (now, root)):
            try:
                side[rel] = os.lstat(base / rel)
            except FileNotFoundError:
                pass
    finished = {}
    for rel in sorted(set(saved) | set(now)):
        before, after = saved.get(rel), now.get(rel)
        if before is not None and after is not None and before.st_size == after.st_size \
                and before.st_mtime_ns == after.st_mtime_ns:
            continue
        finished[rel] = {"now": _fingerprint(root / rel) if after is not None else None,
                         "saved": _sha256(clone / rel) if before is not None else None}
    entry["finished"] = finished


async def finish(run_id: int | None) -> None:
    """How the run left every path it changed, and the saved copies' hashes; releases its folders."""
    if run_id is None:
        return
    for runs in _touching.values():
        runs.discard(int(run_id))
    data = manifest(run_id) if int(run_id) in _live else None
    _live.discard(int(run_id))
    if data is None:
        _locks.pop(int(run_id), None)
        return

    def work() -> None:
        for entry in data["roots"]:
            if entry["skipped"] is None:
                _finish_root(int(run_id), entry)
        _save(int(run_id), data)
    try:
        await asyncio.to_thread(work)
    except Exception:  # noqa: BLE001 — a checkpoint never fails the run it belongs to
        logger.warning("checkpoints: finishing run %s failed", run_id, exc_info=True)
    _locks.pop(int(run_id), None)
