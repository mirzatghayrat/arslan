"""Each run's own temp folder, handed to its commands as TMPDIR (SBX-3 §1a, v0.1.64).

Commands used to share the server process's temp folder, and the sandbox let them write the shared
per-user /var/folders/… parent (with the user cache C), /private/tmp and /private/var/tmp. Now a run
gets a 0700 folder of its own under the per-user T folder, and that folder is the only temp a
sandboxed command may write. It sits outside every protected root, because the last rule wins and a
folder under Arslan's data would be denied. Every command of the run shares it.

The folder goes when the run ends and none of the process groups its commands started is left. A
command can leave a process running (`cmd &`, `nohup`, a dev server): then the folder stays, and the
next start's `sweep()` removes it once those processes are gone. A process that outlives its folder
is a compatibility issue, not a security one. S3's checkpoint does not cover temp, so this is what
keeps anything a run left in temp from outliving it.

Each folder's process groups are recorded next to it in the root (`<folder>.groups`), not inside it:
the folder is the command's to write, the root is not.
"""
from __future__ import annotations

import hashlib
import itertools
import logging
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

_folders: dict[int, Path] = {}
_one_off = itertools.count(-1, -1)          # keys for commands outside any run


def root() -> Path:
    """Where the runs' folders live: under the per-user temp folder, one root per Arslan data folder,
    so two Arslan instances never sweep each other's runs."""
    from server import config
    from server.services.sandbox_profile import real
    tag = hashlib.sha256(str(real(config.data_dir())).encode()).hexdigest()[:12]
    return real(tempfile.gettempdir()) / f"arslan-runs-{tag}"


def folder(key: int) -> Path:
    """The folder of run `key` (a run id), made on first use: 0700, resolved."""
    path = _folders.get(key)
    if path is None or not path.is_dir():
        base = root()
        base.mkdir(mode=0o700, exist_ok=True)
        path = Path(tempfile.mkdtemp(prefix=f"run-{key}-", dir=base)).resolve()     # mkdtemp makes it 0700
        _folders[key] = path
    return path


def _record(path: Path) -> Path:
    return path.with_name(path.name + ".groups")


def started(key: int, group: int) -> None:
    """A command of run `key` started process group `group`."""
    path = _folders.get(key)
    if path is not None:
        with open(_record(path), "a", encoding="utf-8") as out:
            out.write(f"{group}\n")


def _groups(path: Path) -> list[int]:
    try:
        return [int(word) for word in _record(path).read_text(encoding="utf-8").split() if word.isdigit()]
    except OSError:
        return []


def _alive(group: int) -> bool:
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True             # someone else's group now (a reused id): keep the folder, the safe way
    return True


def _remove(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)          # never follows a link the command left inside
    _record(path).unlink(missing_ok=True)


def finish(key: int | None) -> None:
    """Run `key` ended, however it ended: its folder goes now, unless a process group of its commands is
    still there (then the next start's sweep removes it)."""
    path = _folders.pop(key, None) if key is not None else None
    if path is not None and not any(_alive(group) for group in _groups(path)):
        _remove(path)


@contextmanager
def for_command(run_id: int | None) -> Iterator[tuple[int, Path]]:
    """The key and temp folder for one command: its run's, or, outside any run, a folder of its own that
    goes with it."""
    key = run_id if run_id is not None else next(_one_off)
    try:
        yield key, folder(key)
    finally:
        if run_id is None:
            finish(key)


def sweep() -> int:
    """At start: remove every folder (and record) an earlier start left whose process groups are all
    gone. Returns how many folders went."""
    base = root()
    if not base.is_dir():
        return 0
    live = set(_folders.values())
    removed = 0
    for path in base.iterdir():
        if path.suffix == ".groups":
            if not path.with_suffix("").exists():
                path.unlink(missing_ok=True)
            continue
        if path.is_symlink() or not path.is_dir() or path in live:
            continue
        if not any(_alive(group) for group in _groups(path)):
            _remove(path)
            removed += 1
    return removed


def _reset_for_tests() -> None:
    _folders.clear()
