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
  can be rebuilt are left out and listed: by name (EXCLUDED), and any folder holding a `pyvenv.cfg`, a
  Python environment whatever its name (M3 #8). One rule everywhere (count, copy, finish, per-file saves,
  restore): such a folder is left out when it held the marker at the save (recorded as `marked`, so a run
  that deletes the marker does not turn its files into "made by the run"), or holds it now and the copy does
  not hold it (an environment the run made; a folder that was saved stays undoable even if the run makes it
  an environment, ⓪Plan's review). One the run made is recorded too, at its first write_file or at `finish`.
  The marker is never read through a link, `.git` is never left out, nor anything in it. So are Arslan's own paths, and secret-shaped files (`.env`, keys:
  never copied into checkpoints, so never undone, ⓪Plan's review). FIFOs,
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
  created it). "Made by the run" means absent when the folder was saved: what existed but is not in the
  copy (a copy that failed, a secret-shaped file, an unreadable folder) is listed as not saved instead,
  never trashed (⓪Plan's review, 🔴2). Paths the run did not change are not hashed: a copy keeps size and
  mtime. Also the
  folders it made or removed, and for `.git` the saved one's files but objects, by hash.
- **Putting back** (`restore_files`), path by path, only what is still as its run left it: the saved
  copy (bytes, mode, mtime) after checking its hash, or the Trash for what the run made; anything changed
  since is kept and listed. Every path read from the manifest must stay inside its folder (🔴1, 🟠3: commands
  outside the sandbox can write the manifest). A try with failures can be tried again for what failed. No folder of a path is followed through a link. `.git` goes back whole or
  not at all. Later runs on the same folder are undone first, newest first. Refused while a run is
  changing the folder, for a run that never finished, and a second time. Nested repositories
  (`sub/.git`) go back file by file, like any folder.
- **How much, how long:** what all checkpoints hold apart from the originals, measured when each run
  ends, stays under QUOTA_BYTES (oldest out first); older than KEEP_S goes (checked at most hourly).
  Never a run still going, nor the one that just ended. `summary` is what the API shows.
"""
from __future__ import annotations

import asyncio
import contextlib
import ctypes
import difflib
import errno
import hashlib
import json
import logging
import os
import plistlib
import re
import secrets
import shutil
import stat
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

#: Folders that can be rebuilt, left out of the copy (the undo box says so). `.git` is kept.
EXCLUDED = frozenset({"node_modules", ".venv", "venv", "__pycache__", "build", "dist", ".next", "target",
                      "DerivedData", ".build"})
#: A folder holding this file is a Python environment (PEP 405), left out like EXCLUDED whatever its name. M3 #8:
#: an environment Arslan made, not named venv or .venv, held 29,164 of a working folder's 35,119 files, so the
#: whole folder was over MAX_FILES and nothing could be undone.
VENV_MARKER = "pyvenv.cfg"
MAX_FILES = 20_000
MAX_BYTES = 5 * 1024 ** 3
MIN_FREE = 5 * 1024 ** 3
#: Without clonefile (Linux CI, a non-APFS volume) a file is copied only up to this size. DELETE-BY: when
#: CI no longer runs these tests on Linux and Arslan no longer supports non-APFS volumes (card S3).
COPY_MAX = 50 * 1024 ** 2
SLOW_S = 2.0                           # a folder copy that took longer is noted (the card's cost watch)
#: What all checkpoints hold apart from the originals stays under this; the oldest go first.
QUOTA_BYTES = 10 * 1024 ** 3
KEEP_S = 7 * 24 * 3600                 # a checkpoint older than this goes ...
TIDY_EVERY_S = 3600                    # ... checked at most this often (permission_store._prune's way)
_last_tidy = {"at": 0.0}
_CLONE_NOFOLLOW = 0x0001
_CLONE_NAME = re.compile(r"copy-\d+")   # a folder copy's own name in the manifest; nothing else is read
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
    _last_tidy["at"] = 0.0


def _make_root() -> None:
    root = root_dir()
    root.mkdir(parents=True, exist_ok=True)
    if not _tm_excluded(root):        # put back when it went missing, not only at creation (⓪Plan's review)
        _tm_exclude(root)


def _tm_excluded(path: Path) -> bool:
    if sys.platform != "darwin":
        return True
    libc = _libc()
    libc.getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t,
                              ctypes.c_uint32, ctypes.c_int]
    libc.getxattr.restype = ctypes.c_ssize_t
    return libc.getxattr(os.fsencode(path), _TM_EXCLUDE, None, 0, 0, 0) >= 0


def _tm_exclude(path: Path) -> None:
    # Kept out of Time Machine: these are copies of the user's own files, a week at most. The attribute
    # `tmutil addexclusion` writes, set directly: tmutil itself takes ~11 s (measured 2026-10-22).
    value = plistlib.dumps("com.apple.backupd", fmt=plistlib.FMT_BINARY)
    libc = _libc()
    libc.setxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t,
                              ctypes.c_uint32, ctypes.c_int]
    if libc.setxattr(os.fsencode(path), _TM_EXCLUDE, value, len(value), 0, 0) != 0:
        logger.warning("checkpoints: could not exclude %s from Time Machine", path)


def _same_volume(a: Path, b: Path) -> bool:
    return os.stat(a).st_dev == os.stat(b).st_dev


def other_volume(folder: Path | None) -> bool:
    """Settings' hint (S3b): changes in a folder on another volume than the data folder can't be undone."""
    from server import config
    try:
        return folder is not None and not _same_volume(folder, config.data_dir())
    except OSError:
        return False


def _free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def _protected() -> list[Path]:
    from server.services import command_sandbox
    return [Path(p).resolve() for p in command_sandbox.default_protected()]


def _skip_dir(path: Path, name: str, protected: list[Path], in_git: bool = False) -> bool:
    # Inside `.git` nothing is left out: a branch `feature/build/x` is a folder named `build`.
    return (name in EXCLUDED and not in_git) or any(path == p or p in path.parents for p in protected)


def _marked(folder: Path) -> bool:
    """`folder` itself holds a regular VENV_MARKER. lstat: a marker that is a link is not one."""
    try:
        return stat.S_ISREG(os.lstat(folder / VENV_MARKER).st_mode)
    except OSError:
        return False


def _marked_at(root: Path, rel: str) -> bool:
    """`root/rel` holds the marker, reached through no link: `rel` comes from a copy or the manifest, and a
    folder of it may have become a link since (the marker is only ever the folder's own)."""
    folder = root / rel
    return os.path.realpath(folder) == str(folder) and _marked(folder)


def _left_out_at(parts: tuple[str, ...], root: Path | None = None, marked: frozenset[str] = frozenset(),
                 copy: Path | None = None) -> str | None:
    """The folder of `parts` the copy leaves out, met before any `.git`, or None: a rebuildable name, or a
    Python environment, recorded in `marked` or holding the marker under `root` now where `copy` (the saved
    copy) does not hold it. A folder that was saved stays in, marker or not."""
    for i, part in enumerate(parts):
        if part == ".git":
            return None
        rel = "/".join(parts[:i + 1])
        if part in EXCLUDED or rel in marked:
            return rel
        if root is not None and _marked_at(root, rel) and not (copy is not None and os.path.isdir(copy / rel)):
            return rel
    return None


def _left_out(parts: tuple[str, ...], root: Path | None = None, marked: frozenset[str] = frozenset(),
              copy: Path | None = None) -> bool:
    return _left_out_at(parts, root, marked, copy) is not None


def _in_git(rel: str) -> bool:
    return rel == ".git" or rel.startswith(".git/")


def _contained(rel: str) -> bool:
    """A relative path that stays inside its folder: not absolute, no `.`/`..` part, not empty. Every path
    a restore reads from the manifest is checked (⓪Plan's review, 🔴1/🟠3: a command outside the sandbox can
    write the manifest, and `root/".build/.."` is the root itself)."""
    path = Path(rel)
    return bool(rel) and "\x00" not in rel and not path.is_absolute() \
        and not any(part in ("", ".", "..") for part in rel.split("/"))


def _under(rel: str, folders: list[str]) -> bool:
    return any(folder == "." or rel == folder or rel.startswith(folder + "/") for folder in folders)


def _walk(root: Path, protected: list[Path], excluded: set[str], not_regular: list[str],
          folders: list[str] | None = None, git: bool = False, unreadable: list[str] | None = None,
          marked: frozenset[str] = frozenset(), found: list[str] | None = None, copy: Path | None = None,
          live: bool = True):
    """(relative path, absolute path, lstat) for each regular file under `root`, never following a link.
    Skipped directories go into `excluded`, everything that is not a regular file into `not_regular`,
    every directory kept into `folders`, and what could not be read into `unreadable`, when given.
    `git`: `root` is a `.git`. A Python environment is skipped too, never `.git` or anything in it: a folder in
    `marked`, or, when `live`, one holding the marker now that `copy` (the saved copy) does not hold; those
    found by the marker go into `found`. A walk of the copy itself passes `live=False`: it has no markers."""
    def cannot_read(exc: OSError) -> None:
        if unreadable is not None and exc.filename:
            unreadable.append(str(Path(exc.filename).relative_to(root)))
    for top, dirs, files in os.walk(root, followlinks=False, onerror=cannot_read):
        here = Path(top)
        in_git = git or ".git" in here.relative_to(root).parts
        keep = []
        for name in dirs:
            path = here / name
            rel = str(path.relative_to(root))
            if os.path.islink(path):
                not_regular.append(rel)
            elif _skip_dir(path, name, protected, in_git):
                excluded.add(name if name in EXCLUDED else rel)
            elif not in_git and name != ".git" and (rel in marked or (
                    live and _marked(path) and not (copy is not None and os.path.isdir(copy / rel)))):
                excluded.add(rel)
                if found is not None and rel not in marked:
                    found.append(rel)
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
                if unreadable is not None:
                    unreadable.append(str(path.relative_to(root)))
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
    # A copy goes in under a temporary name and takes its own only when whole: copy2 writes the target
    # before it can fail (ENOSPC, EIO, copystat), and half a file in the copy would be put back over an
    # untouched one (⓪Plan's re-check). A crash in between leaves no manifest entry, so nothing restores it.
    part = dst.with_name(f".{dst.name[:200]}.{secrets.token_hex(4)}.part")
    try:
        shutil.copy2(src, part, follow_symlinks=False)
        os.replace(part, dst)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(part)
        raise
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
    from server.services.workspace_paths import is_secret_name
    not_regular: list[str] = []
    failed: list[str] = []
    secret: list[str] = []
    folders: list[str] = []
    unreadable: list[str] = []
    # What existed but is not in the copy, by size and mtime only (never its content): a file that could
    # not be copied, or a secret-shaped one, which is never copied (⓪Plan's review). Undo never treats
    # either as made by the run (🔴2), and lists it as not saved when the run changed it.
    unsaved: dict[str, list[int]] = {}
    methods: set[str] = set()
    started = time.monotonic()
    dest.mkdir(parents=True)
    marked: list[str] = []
    for rel, path, st in _walk(root, protected, excluded, not_regular, folders, unreadable=unreadable, found=marked):
        if is_secret_name(path.name):
            secret.append(rel)
            unsaved[rel] = [st.st_size, st.st_mtime_ns]
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            methods.add(_clone_file(path, target, st.st_size))
        except OSError:
            failed.append(rel)
            unsaved[rel] = [st.st_size, st.st_mtime_ns]
    for rel in folders:  # empty ones too: a folder missing from the copy is one the run made
        (dest / rel).mkdir(parents=True, exist_ok=True)
    return {"excluded": sorted(excluded), "marked": sorted(marked), "not_regular": sorted(not_regular),
            "failed": sorted(failed),
            "secret": sorted(secret), "unreadable": sorted(unreadable), "unsaved": unsaved,
            "method": "clonefile" if "clonefile" in methods else ("copy" if methods else None),
            "seconds": round(time.monotonic() - started, 3)}


def _save_root(run_id: int, root: Path, index: int) -> dict:
    entry = {"path": str(root), "clone": f"copy-{index}", "skipped": None, "excluded": [], "marked": [],
             "not_regular": [],
             "failed": [], "secret": [], "unreadable": [], "unsaved": {}, "written": [], "method": None,
             "seconds": 0.0, "slow": False, "finished": None}
    protected = _protected()
    if not _same_volume(root, root_dir()):
        entry["skipped"] = "other_volume"
    elif _free_bytes(root_dir()) < MIN_FREE:
        entry["skipped"] = "low_disk"
    else:
        entry["skipped"] = _count(root, protected)
    if entry["skipped"] is None:
        entry.update(_copy_tree(root, _run_dir(run_id) / entry["clone"], protected))
        entry["slow"] = entry["seconds"] > SLOW_S
        if entry["slow"]:
            logger.info("checkpoints: saving a folder for run %s took %.1f s", run_id, entry["seconds"])
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
    with _restoring:  # a first change waits for a restore in progress; restore checks the runs under it
        _ensure_locked(run_id, roots, written)


def _ensure_locked(run_id: int, roots: list[Path], written: Path | None) -> None:
    _make_root()
    data = manifest(run_id) if run_id in _live else None
    if data is None:
        from server.services import personal_context
        ctx = personal_context.current()
        _live.add(run_id)  # first: _tidy never removes a run that is going
        shutil.rmtree(_run_dir(run_id), ignore_errors=True)  # an earlier run's, if any: not this one's
        _run_dir(run_id).mkdir(parents=True, exist_ok=True)
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
        marked = entry.setdefault("marked", [])
        left = _left_out_at(rel.parts[:-1], root, frozenset(marked), _run_dir(run_id) / entry["clone"]) \
            if _contained(str(rel)) else None
        if left is None or str(rel) in entry["written"]:
            return False
        if Path(left).name not in EXCLUDED and left not in marked:
            # An environment the run made: recorded before its folder appears in the copy, so `finish`, the
            # copy's walk and a restore keep leaving it out.
            marked.append(left)
            entry["excluded"] = sorted(set(entry["excluded"]) | {left})
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
                entry["unsaved"][str(rel)] = [st.st_size, st.st_mtime_ns]
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
    saved_folders: list[str] = []
    now_folders: list[str] = []
    marked = frozenset(entry.get("marked", []))   # both sides leave out the same environments
    saved = {rel: st for rel, _, st in _walk(clone, [], set(), [], saved_folders, marked=marked, live=False)}
    made: list[str] = []                          # environments the run made, found by their marker
    now = {rel: st for rel, _, st in _walk(root, protected, set(), [], now_folders, marked=marked, found=made,
                                           copy=clone)}
    if made:                                      # the undo window lists them; a restore leaves them out
        entry["marked"] = sorted(marked | set(made))
        entry["excluded"] = sorted(set(entry["excluded"]) | set(made))
    for rel in entry["written"]:  # under left-out folders, which neither walk enters
        if not _contained(rel):
            continue
        for side, base in ((saved, clone), (now, root)):
            try:
                side[rel] = os.lstat(base / rel)
            except FileNotFoundError:
                pass
    finished, not_saved = {}, []
    for rel in sorted(set(saved) | set(now)):
        before, after = saved.get(rel), now.get(rel)
        if before is not None and after is not None and before.st_size == after.st_size \
                and before.st_mtime_ns == after.st_mtime_ns:
            continue
        # 🔴2: "made by the run" means absent when the folder was saved. What existed but is not in the copy
        # is never that: unchanged, it is nothing; changed or deleted, it is listed as not saved.
        if before is None and rel in entry["unsaved"]:
            if after is None or [after.st_size, after.st_mtime_ns] != entry["unsaved"][rel]:
                not_saved.append(rel)
            continue
        if before is None and _under(rel, entry["unreadable"]):
            not_saved.append(rel)              # it could not be read at save: whether it existed is unknown
            continue
        finished[rel] = {"now": _fingerprint(root / rel) if after is not None else None,
                         "saved": _sha256(clone / rel) if before is not None else None}
    entry["finished"], entry["not_saved"] = finished, not_saved
    saved_folders = [rel for rel in saved_folders if not _in_git(rel)]
    now_folders = [rel for rel in now_folders if not _in_git(rel)]
    entry["folders_made"] = sorted(set(now_folders) - set(saved_folders))
    entry["folders_removed"] = sorted(set(saved_folders) - set(now_folders))
    # Q3 for `.git`, which goes back whole: the saved one's files but objects, by hash.
    entry["git_saved"] = _git_hashes(clone / ".git") if any(_in_git(rel) for rel in finished) else {}


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
        data["own_bytes"] = _own_bytes(int(run_id), data)
        _save(int(run_id), data)
        _tidy(int(run_id))
    try:
        await asyncio.to_thread(work)
    except Exception:  # noqa: BLE001 — a checkpoint never fails the run it belongs to
        logger.warning("checkpoints: finishing run %s failed", run_id, exc_info=True)
    _locks.pop(int(run_id), None)



def _own_bytes(run_id: int, data: dict) -> int:
    """What a checkpoint holds apart from the originals, when its run ends: a plain copy all of it; a
    clone the files whose original the run changed or deleted (they no longer share blocks). Changes
    made after the run are not counted."""
    total = 0
    for entry in data["roots"]:
        if entry["skipped"] is not None:
            continue
        clone = _run_dir(run_id) / entry["clone"]
        if entry["method"] == "copy":
            rels = [rel for rel, _, _ in _walk(clone, [], set(), [], marked=frozenset(entry.get("marked", [])),
                                               live=False)] + entry["written"]
        else:
            rels = [rel for rel, left in entry["finished"].items() if left["saved"] is not None]
        for rel in rels:
            with contextlib.suppress(OSError):
                total += os.lstat(clone / rel).st_size
    return total


def _tidy(newest: int) -> None:
    """Older than KEEP_S out (at most every TIDY_EVERY_S), then the oldest out while over QUOTA_BYTES.
    Never a run still going, nor `newest`: the turn that just ended can always be undone. Never while a
    restore is reading copies (⓪Plan's review)."""
    with _restoring:
        _tidy_locked(newest)


def _tidy_locked(newest: int) -> None:
    ids = sorted(int(p.name) for p in root_dir().iterdir() if p.name.isdigit())
    keep = _live | {newest}
    now = time.time()
    if now - _last_tidy["at"] >= TIDY_EVERY_S:
        _last_tidy["at"] = now
        for rid in ids:
            data = manifest(rid)
            if rid not in keep and (data is None or data["created_at"] < now - KEEP_S):
                shutil.rmtree(_run_dir(rid), ignore_errors=True)
    sizes = {rid: data.get("own_bytes", 0) for rid in ids if (data := manifest(rid)) is not None}
    total = sum(sizes.values())
    for rid in sorted(sizes):
        if total <= QUOTA_BYTES:
            break
        if rid not in keep:
            shutil.rmtree(_run_dir(rid), ignore_errors=True)
            total -= sizes[rid]


def changes(run_id: int, not_before: float) -> dict | None:
    """WB1-3: what this run did in the user's folders, path by path, for Overview's Changes: `made` (absent
    when the folder was saved), `deleted` (gone when the run ended) or `edited`; and whether it was undone.
    None when there is no copy, or the copy is an earlier run's under the same id (`not_before`): the same
    rule as `summary` and a restore, so the list covers exactly the turns an undo can still take back (②Main's
    review of #545: no separate age rule). Only what an undo can put back is listed: changes it could not save
    (`not_saved`) are not. `.git` is left out (it goes back whole); paths are relative to their folder, with
    the folder alongside. One manifest read; a caller runs it off the event loop."""
    data = manifest(run_id)
    if data is None or data["created_at"] < not_before:
        return None
    out = []
    for entry in data["roots"]:
        for rel, state in sorted((entry.get("finished") or {}).items()):
            if _in_git(rel):
                continue
            kind = "made" if state.get("saved") is None else "deleted" if state.get("now") is None else "edited"
            out.append({"folder": entry["path"], "path": rel, "kind": kind})
    return {"paths": out, "undone": bool(data.get("restored_at"))}


#: DIFF1: a side larger than this, or with more lines, is not compared (the reader keeps just "Edited").
DIFF_MAX_BYTES = 1024 ** 2
DIFF_MAX_LINES = 20_000


class NoDiff(Exception):
    """Why a path has no line diff: `not_listed` (not a change an undo can still take back), `hidden` (a
    dot-path or a secret-shaped name, which the reader never shows), `too_big`, `not_text`, or `copy_changed`
    (the saved copy no longer has the hash `finish` recorded)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _read_side(folder: Path, rel: str) -> bytes | None:
    """The file at folder/rel, None when there is none. No folder of the path and not the file itself is
    followed through a link (as a restore); a side that is not a regular file is not text."""
    parts = Path(rel).parts
    try:
        fd = _open_folder(folder, parts[:-1], create=False)
    except FileNotFoundError:
        return None
    try:
        try:
            handle = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            return None
        except OSError as exc:
            if exc.errno == errno.ELOOP:          # a link where the file was
                raise NoDiff("not_text") from None
            raise
        with os.fdopen(handle, "rb") as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode):
                raise NoDiff("not_text")
            if st.st_size > DIFF_MAX_BYTES:
                raise NoDiff("too_big")
            data = f.read(DIFF_MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > DIFF_MAX_BYTES:                # grew between the fstat and the read
        raise NoDiff("too_big")
    return data


def _text_lines(data: bytes | None) -> list[str]:
    if data is None:
        return []
    if b"\0" in data:
        raise NoDiff("not_text")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise NoDiff("not_text") from None
    lines = text.splitlines()
    if len(lines) > DIFF_MAX_LINES:
        raise NoDiff("too_big")
    return lines


def diff(run_id: int, not_before: float, folder: str, rel: str) -> dict:
    """DIFF1: one path a run changed, as lines: the saved copy (before the run) against the file now, the
    view Overview's Changes opens. Only a path `changes` lists for the run (same manifest, same
    `not_before` rule: it exists only while the turn can still be undone), never a dot-path or a
    secret-shaped name (file_reader's rule). `lines` is every line with its op (" ", "-", "+") and its old
    and new numbers, so the reader can fold what did not change; `since` is True when the file changed
    after the run ended (the diff is still against the file now). Read only; raises NoDiff. A caller runs
    it off the event loop."""
    from server.services.workspace_paths import is_secret_name
    data = manifest(run_id)
    if data is None or data["created_at"] < not_before:
        raise NoDiff("not_listed")
    entry = next((r for r in data["roots"] if r["path"] == folder and r["skipped"] is None), None)
    state = (entry.get("finished") or {}).get(rel) if entry else None
    if state is None or not _contained(rel) or _in_git(rel):
        raise NoDiff("not_listed")
    if any(part.startswith(".") for part in Path(rel).parts) or is_secret_name(Path(rel).name):
        raise NoDiff("hidden")
    before = None
    if state.get("saved") is not None:
        if not _CLONE_NAME.fullmatch(str(entry.get("clone"))):   # the manifest can be written outside the sandbox
            raise NoDiff("copy_changed")
        before = _read_side(_run_dir(run_id) / entry["clone"], rel)
        if before is None or hashlib.sha256(before).hexdigest() != state["saved"]:
            raise NoDiff("copy_changed")
    after = _read_side(Path(folder), rel)
    old, new = _text_lines(before), _text_lines(after)
    now = state.get("now")
    since = (hashlib.sha256(after).hexdigest() if after is not None else None) != (now or {}).get("sha256")
    lines: list[list] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if op == "equal":
            lines += [[" ", i + 1, j1 + k + 1, old[i]] for k, i in enumerate(range(i1, i2))]
            continue
        lines += [["-", i + 1, None, old[i]] for i in range(i1, i2)]
        lines += [["+", None, j + 1, new[j]] for j in range(j1, j2)]
    return {"kind": "made" if state.get("saved") is None else "deleted" if now is None else "edited",
            "added": sum(1 for line in lines if line[0] == "+"),
            "removed": sum(1 for line in lines if line[0] == "-"),
            "since": since, "lines": lines}


def summary(run_id: int, not_before: float) -> dict:
    """What GET /runs/{id}/checkpoint answers. A copy made before `not_before` (the run's start) is an
    earlier run's under the same id, so it is not this run's."""
    data = manifest(run_id)
    if data is None or data["created_at"] < not_before:
        return {"exists": False}
    roots = data["roots"]
    left = [one for entry in roots for one in (entry["finished"] or {}).values()]
    saved = {entry["path"] for entry in roots if entry["skipped"] is None}
    return {
        "exists": True,
        "changed": sum(1 for one in left if one["saved"] is not None),
        "created": sum(1 for one in left if one["saved"] is None),
        "skipped": [{"path": entry["path"], "reason": entry["skipped"]} for entry in roots if entry["skipped"]],
        "excluded": sorted({name for entry in roots for name in entry["excluded"]}),
        "overlap": data["overlap"],
        "later": [] if data.get("restored_at") else [rid for rid, _ in _later(run_id, saved)],
        "running": run_id in _live,
        "restored_at": data.get("restored_at"),
        "expires_at": datetime.fromtimestamp(data["created_at"] + KEEP_S, timezone.utc)
                      .replace(tzinfo=None).isoformat(),
    }

# ── Putting files back (C2) ───────────────────────────────────────────────────────────────────────

class Refused(Exception):
    """`code`: none (nothing saved), already (put back before), running (`runs` are changing the
    folder now), not_finished (`runs` ended without `finish`: how they left the folder is unknown)."""

    def __init__(self, code: str, runs: list[int] | None = None) -> None:
        super().__init__(code)
        self.code, self.runs = code, runs or []


_restoring = threading.Lock()
# macOS 11+: no segment of the path may be a link at the open; elsewhere the last one (the folders are
# opened one by one below). As file_tools._NOFOLLOW.
_NOFOLLOW = getattr(os, "O_NOFOLLOW_ANY", 0) or os.O_NOFOLLOW


async def restore_files(run_id: int) -> dict:
    """Put the folders saved for `run_id` back as they were before it, the later runs that changed
    them first, newest first. Path by path, only what is still as its run left it. Raises Refused."""
    return await asyncio.to_thread(_restore_sync, int(run_id))


async def check_restore(run_id: int) -> None:
    """Raise Refused when `restore_files` would refuse now (S3b's "both" checks before it changes anything)."""
    await asyncio.to_thread(_check_sync, int(run_id))


def _check_sync(run_id: int) -> None:
    with _restoring:
        _chain(run_id)


def _chain(run_id: int) -> list[tuple[int, dict]]:
    """The runs to put back, newest first, after the checks a restore makes. Raises Refused."""
    data = manifest(run_id) if run_id not in _live else None
    roots = {e["path"] for e in data["roots"] if e["skipped"] is None} if data else set()
    running = sorted({r for root in roots for r in _touching.get(root, set())} | ({run_id} & _live))
    if running:
        raise Refused("running", running)
    if not roots:
        raise Refused("none")
    if data.get("restored_at"):
        raise Refused("already")
    chain = _later(run_id, roots) + [(run_id, data)]
    unfinished = [rid for rid, d in chain if any(e["skipped"] is None and e["finished"] is None
                                                for e in d["roots"])]
    if unfinished:
        raise Refused("not_finished", unfinished)
    return chain


def _restore_sync(run_id: int) -> dict:
    with _restoring:
        chain = _chain(run_id)
        return {"run_id": run_id, "later": [rid for rid, _ in chain[:-1]],
                "runs": [_restore_run(rid, d) for rid, d in chain]}


def _later(run_id: int, roots: set[str]) -> list[tuple[int, dict]]:
    """Runs after `run_id` with a copy of one of `roots` not put back yet, newest first."""
    found = []
    for path in root_dir().iterdir() if root_dir().is_dir() else ():
        other = manifest(int(path.name)) if path.name.isdigit() and int(path.name) > run_id else None
        if other and not other.get("restored_at") \
                and roots & {e["path"] for e in other["roots"] if e["skipped"] is None}:
            found.append((int(path.name), other))
    return sorted(found, key=lambda pair: pair[0], reverse=True)


def _restore_run(run_id: int, data: dict) -> dict:
    out = {"run_id": run_id, "restored": [], "trashed": [], "user_changed": [], "failed": [], "not_saved": [],
           "git": None}
    done = set(data.get("restored_paths", []))       # put back by an earlier try that had failures
    for entry in data["roots"]:
        if entry["skipped"] is None:
            _restore_root(run_id, entry, out, done)
    done |= set(out["restored"]) | set(out["trashed"]) | ({".git"} if out["git"] in ("restored", "trashed") else set())
    data["restored_paths"], data["restore"] = sorted(done), out
    # A try with failures can be tried again for what failed (⓪Plan's review); a whole one cannot.
    data["restore_failed_at" if out["failed"] else "restored_at"] = time.time()
    _save(run_id, data)
    return out


def _root_ok(root: Path) -> bool:
    """A folder the manifest names: absolute, not Arslan's data folder, not a protected path."""
    from server import config
    data = config.data_dir().resolve()
    return root.is_absolute() and not (root == data or data in root.parents) \
        and not any(root == p or p in root.parents for p in _protected())


def _restore_root(run_id: int, entry: dict, out: dict, done: set[str]) -> None:
    root, finished = Path(entry["path"]), entry["finished"]
    out["not_saved"].extend(entry.get("not_saved", []))
    if not _CLONE_NAME.fullmatch(str(entry.get("clone"))) or not _root_ok(root):
        out["failed"].extend(rel for rel in finished if rel not in done)     # a manifest not as saved
        return
    clone = _run_dir(run_id) / entry["clone"]
    marked = frozenset(entry.get("marked", []))
    for rel in entry["folders_removed"]:
        if _contained(rel) and not _left_out(Path(rel).parts, root, marked, clone):
            with contextlib.suppress(OSError):
                os.close(_open_folder(root, Path(rel).parts))
    for rel, left in finished.items():
        if rel in done or _in_git(rel):
            continue
        if not _contained(rel):
            out["failed"].append(rel)
            continue
        # Never into a folder the copy left out, unless write_file saved that file on its own (M3 #8):
        # `finish` lists none, so one here comes from a manifest written since; the folder is left as it is.
        if rel not in entry["written"] and _left_out(Path(rel).parts[:-1], root, marked, clone):
            out["not_saved"].append(rel)
            continue
        if _fingerprint(root / rel) != left["now"]:
            out["user_changed"].append(rel)
            continue
        try:
            if left["saved"] is None:
                _trash_inside(root, rel)
                out["trashed"].append(rel)
            else:
                _put_back(root, rel, clone / rel, left["saved"])
                out["restored"].append(rel)
        except (OSError, ValueError):
            out["failed"].append(rel)
    for rel in sorted(entry["folders_made"], reverse=True):  # deepest first, and only when empty
        if not _contained(rel) or _left_out(Path(rel).parts, root, marked, clone):
            continue
        with contextlib.suppress(OSError):
            fd = _open_folder(root, Path(rel).parts[:-1], create=False)
            try:
                os.rmdir(Path(rel).name, dir_fd=fd)
            finally:
                os.close(fd)
    if os.path.isfile(root / ".git") and not os.path.islink(root / ".git"):
        out["git"] = "outside"     # a worktree's or submodule's pointer: its repository, commits too, is elsewhere
    elif ".git" not in done and any(_in_git(rel) for rel in finished):
        try:
            out["git"] = _restore_git(root, clone, entry)
        except OSError:
            out["git"] = "failed"


def _open_folder(root: Path, parts: tuple[str, ...], create: bool = True) -> int:
    """A descriptor for root/parts, each folder made where missing and opened without following a link."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            if create:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, dir_fd=fd)
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def _put_back(root: Path, rel: str, src: Path, saved: str) -> None:
    """The saved copy back at `rel`: its bytes, mode and mtime, into a temp file in the opened folder,
    then os.replace (a link there is replaced, not followed; a hard link's other name keeps its content,
    as F4b). Raises ValueError when the copy no longer has the hash `finish` recorded (Q3)."""
    if not _contained(rel):
        raise ValueError(f"not a path inside the folder: {rel}")
    parts = Path(rel).parts
    folder = _open_folder(root, parts[:-1])
    tmp = f".{parts[-1].encode()[:200].decode(errors='ignore')}.{secrets.token_hex(4)}.undo"
    try:
        with os.fdopen(os.open(src, os.O_RDONLY | _NOFOLLOW), "rb") as source:
            st = os.fstat(source.fileno())
            digest = hashlib.sha256()
            out = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder)
            try:
                with os.fdopen(out, "wb") as target:
                    for block in iter(lambda: source.read(1 << 20), b""):
                        digest.update(block)
                        target.write(block)
                    target.flush()
                    os.fchmod(target.fileno(), stat.S_IMODE(st.st_mode))
                    os.utime(target.fileno(), ns=(st.st_atime_ns, st.st_mtime_ns))
                if digest.hexdigest() != saved:
                    raise ValueError(f"the saved copy of {rel} was changed")
                os.replace(tmp, parts[-1], src_dir_fd=folder, dst_dir_fd=folder)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp, dir_fd=folder)
                raise
    finally:
        os.close(folder)


def _trash_inside(root: Path, rel: str) -> None:
    """To the Trash (moved, never deleted), only when no folder of the path is a link."""
    from server.services import capability_install
    if not _contained(rel):
        raise ValueError(f"not a path inside the folder: {rel}")
    parent = (root / rel).parent
    if os.path.realpath(parent) != str(parent):
        raise OSError(errno.ELOOP, "a folder of the path is a link", rel)
    capability_install.to_trash(root / rel, prefix="Arslan undo")


def _git_hashes(git: Path) -> dict | None:
    """sha256 of every file of a `.git` but its objects; None when it holds a link or a special file."""
    odd: list[str] = []
    hashes = {f".git/{rel}": _sha256(path) for rel, path, _ in _walk(git, [], set(), odd, git=True)
              if not rel.startswith("objects/")}
    return None if odd else hashes


def _git_as_left(root: Path, clone: Path, finished: dict) -> bool:
    """Every file of `.git` but objects as the run left it (listed by `finish`, else as saved). A git
    command holding the index (`index.lock`) or any other new file there is a change since the run."""
    now = {f".git/{rel}": st for rel, _, st in _walk(root / ".git", [], set(), [], git=True)
           if not rel.startswith("objects/")}
    saved = {f".git/{rel}": st for rel, _, st in _walk(clone / ".git", [], set(), [], git=True)
             if not rel.startswith("objects/")}
    listed = {rel for rel in finished if _in_git(rel) and not rel.startswith(".git/objects/")}
    if not all(_contained(rel) for rel in listed):
        return False
    for rel in set(now) | set(saved) | listed:
        if rel in listed:
            if _fingerprint(root / rel) != finished[rel]["now"]:
                return False
        elif rel not in now or rel not in saved \
                or (now[rel].st_size, now[rel].st_mtime_ns) != (saved[rel].st_size, saved[rel].st_mtime_ns):
            return False
    return True


def _restore_git(root: Path, clone: Path, entry: dict) -> str:
    """`.git` back whole or not at all (a half-restored repository is worse than none): "restored",
    "trashed" when the run made it, "kept" (untouched) when anything in it changed since the run."""
    saved_git = clone / ".git"
    recorded = entry["git_saved"]
    if not _git_as_left(root, clone, entry["finished"]) or recorded is None \
            or _git_hashes(saved_git) != recorded:
        return "kept"
    if os.path.lexists(root / ".git"):
        _trash_inside(root, ".git")
    if not os.path.lexists(saved_git):
        return "trashed"
    folder = _open_folder(root, ())
    try:
        os.rename(saved_git, ".git", dst_dir_fd=folder)  # the same volume: checked when it was saved
    finally:
        os.close(folder)
    return "restored"
