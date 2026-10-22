"""Tests must never write into the user's real Arslan data dir.

On a developer Mac that dir is where the packaged app keeps the user's brain:
``~/Library/Application Support/Arslan``. Test leaks have landed there before — empty
``spawns/{S,S2,SpawnA,EvalTarget,R,…}/.evolution`` dirs (2026-07), and
``does_not_exist_probe/spawns/{S,S2}/.evolution`` (2026-10-03), which is what made
``test_default_data_dir_import_has_no_filesystem_side_effect`` fail.

Layers, wired from tests/conftest.py and tests/server/conftest.py:

* :func:`pin_suite_data_dir` — the suite's ambient data dir is a throwaway temp dir,
  whatever env pytest was started with.
* :func:`restore_pin` — after every test, a pinned key that test changed outside
  ``monkeypatch`` is put back and the test fails, so the pin cannot be lost silently.
* :func:`inside` — tests/server/conftest.py fails the test whose teardown leaves
  ``server.config`` pointing into the real dir, so the culprit is named.
* :func:`snapshot` / :func:`created` — the session fails if the real dir gained an
  entry it did not have when the run started, whatever the route.
* :func:`pin_suite_home` — ``HOME`` itself is a throwaway dir, so nothing a test resolves
  through it (``~/Arslan``, the default workspace even when ``sys.frozen`` ignores
  ``ARSLAN_DEFAULT_WORKSPACE``) reaches the user's real home.
* :func:`workspace_snapshot` — the user's real ``~/Arslan`` (:data:`REAL_WORKSPACE_DIR`),
  walked in full and REPORTED at the end of the run, not failed: with ``HOME`` pinned no
  test reaches it, so what appears there is the running app's or another process's.

The snapshot does not walk the whole dir. The packaged app may be running during a
test run and writes ``tool_outputs/``, ``artifacts/``, ``backups/`` and its SQLite
sidecars on its own; a guard that fires on that gets ignored. It records the top level
(minus the sidecars) and everything under ``spawns/`` — where every leak so far
landed — and, when the dir does not exist at the start (CI, a fresh machine), any
creation at all. A leak that goes through ``server.config`` into the unwatched subtrees
is still caught by :func:`inside`; one that bypasses config and writes there directly
is not.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from server.profile_paths import default_data_dir

# Resolved when the root conftest imports this module, which it does first: before
# pin_suite_home() re-points HOME, and before any test can patch HOME, sys.platform,
# XDG_DATA_HOME or APPDATA.
#: Handed from the process that pins HOME to the processes it starts (pytest-xdist workers):
#: they inherit the pinned HOME, so they must not read the real one from it.
REAL_HOME_ENV, SUITE_HOME_ENV = "ARSLAN_TEST_REAL_HOME", "ARSLAN_TEST_SUITE_HOME"
REAL_HOME = Path(os.environ.get(REAL_HOME_ENV) or Path.home()).resolve()
REAL_DATA_DIR = default_data_dir().resolve()

# The user's own Arslan folder: what settings_service.default_workspace() falls back to
# when ARSLAN_DEFAULT_WORKSPACE is unset (the packaged app ignores that variable).
REAL_WORKSPACE_DIR = (REAL_HOME / "Arslan").resolve()

# Where each session's HOME lives. Inside the real home on purpose, NOT under the system
# temp dir: the command sandbox lets commands write to the per-user temp folders
# (command_sandbox.temp_roots), and its tests use a folder in HOME as the place a sandboxed
# command must NOT reach. Each session removes its own dir at the end.
SUITE_HOMES = REAL_HOME / ".arslan-pytest-homes"
# Finder writes it whenever the user opens the folder; nothing a test does.
_FINDER_FILES = frozenset({".DS_Store"})

SUITE_DATA_DIR_PREFIX = "arslan-pytest-data-"

# Created and removed by the packaged app's own SQLite connections.
_APP_SIDECARS = frozenset({"arslan.db-wal", "arslan.db-shm", "arslan.db-journal"})
_WATCHED_TREES = ("spawns",)


PINNED_KEYS = ("ARSLAN_DATA_DIR", "ARSLAN_DB_PATH", "ARSLAN_SPAWNS_DIR", "HOME")
_pinned: dict[str, str | None] = {}


_owned: list[Path] = []


def pin_suite_home() -> Path:
    """Point ``HOME`` at this session's own dir and return it.

    Must run before anything resolves ``Path.home()``. Covers ``Path.home()`` and
    ``expanduser("~")``; not ``pwd.getpwuid`` (only ``hands_client.folder()`` uses it, on
    purpose, and that is Hands' folder, not ``~/Arslan``).

    One dir per run, not per process: an xdist worker takes the one its controller made,
    because test ids may contain the home path and every worker must collect the same ids."""
    inherited = os.environ.get(SUITE_HOME_ENV)
    if inherited and Path(inherited).is_dir():
        path = Path(inherited).resolve()
    else:
        SUITE_HOMES.mkdir(exist_ok=True)
        sweep_stale_homes(SUITE_HOMES)
        path = Path(tempfile.mkdtemp(prefix="session-", dir=SUITE_HOMES)).resolve()
        _owned.append(path)
        os.environ[SUITE_HOME_ENV] = str(path)
        os.environ[REAL_HOME_ENV] = str(REAL_HOME)
    os.environ["HOME"] = str(path)
    _pinned["HOME"] = str(path)
    return path


def sweep_stale_homes(parent: Path, *, older_than_s: float = 86_400) -> list[str]:
    """Remove session homes a killed run left behind (no teardown ran); return their names.
    Only this suite's own ``session-*`` dirs, and only a day old, so a live run keeps its own."""
    import time

    removed = []
    for child in parent.glob("session-*"):
        if child.is_dir() and time.time() - child.stat().st_mtime > older_than_s:
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child.name)
    return sorted(removed)


def remove_suite_home() -> None:
    """Remove the session home, in the process that made it (an xdist worker made none)."""
    while _owned:
        shutil.rmtree(_owned.pop(), ignore_errors=True)
        try:
            SUITE_HOMES.rmdir()                  # only once no other run still has one
        except OSError:
            pass


def pin_suite_data_dir() -> Path:
    """Point ``ARSLAN_DATA_DIR`` at a fresh temp dir and return it.

    Must run before the first ``server.config`` import, which builds the settings
    singleton. Unconditional: an unset ``ARSLAN_DATA_DIR`` IS the user's real dir, and
    CI's ``ARSLAN_DATA_DIR=data`` still litters the checkout. ``ARSLAN_DB_PATH`` and
    ``ARSLAN_SPAWNS_DIR`` are dropped so both derive from the pinned dir.
    """
    path = Path(tempfile.mkdtemp(prefix=SUITE_DATA_DIR_PREFIX)).resolve()
    os.environ["ARSLAN_DATA_DIR"] = str(path)
    for key in ("ARSLAN_DB_PATH", "ARSLAN_SPAWNS_DIR"):
        os.environ.pop(key, None)
    _pinned.update({key: os.environ.get(key) for key in PINNED_KEYS})
    return path


def restore_pin() -> list[str]:
    """Put back any pinned key a test changed and did not restore; return their names.

    The pin only holds if nothing takes it away: ``packaging/server_entry._sanitize_env``
    pops ``ARSLAN_DATA_DIR`` from the real ``os.environ`` (correct in the packaged app),
    and on 2026-10-03 one test calling it sent every later test in the run — on main
    too — to the user's real dir: a 100 KB ``tool_outputs/…-command-….txt`` from
    test_run_command_executor and a rewritten ``ui_language`` landed there.
    """
    changed = [key for key, value in _pinned.items() if os.environ.get(key) != value]
    for key in changed:
        if _pinned[key] is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = _pinned[key]
    return changed


def inside(path: str | Path, root: Path = REAL_DATA_DIR) -> bool:
    """True when ``path`` is ``root`` or anywhere under it."""
    resolved = Path(path).resolve()
    return resolved == root or root in resolved.parents


def snapshot(root: Path = REAL_DATA_DIR) -> frozenset[str] | None:
    """The watched entries under ``root`` as relative paths; None if it does not exist."""
    if not root.is_dir():
        return None
    entries = {child.name for child in root.iterdir() if child.name not in _APP_SIDECARS}
    for tree in _WATCHED_TREES:
        for dirpath, dirnames, filenames in os.walk(root / tree):
            for name in (*dirnames, *filenames):
                entries.add((Path(dirpath) / name).relative_to(root).as_posix())
    return frozenset(entries)


def workspace_snapshot(root: Path = REAL_WORKSPACE_DIR) -> frozenset[str] | None:
    """Every entry under ``root`` as relative paths (Finder's files aside); None if absent.

    The whole tree, unlike :func:`snapshot`: a leak into the user's folder would land in
    the folders already there. It is a working folder, small enough to walk twice a run."""
    if not root.is_dir():
        return None
    entries = set()
    for dirpath, dirnames, filenames in os.walk(root):
        for name in (*dirnames, *filenames):
            if name not in _FINDER_FILES:
                entries.add((Path(dirpath) / name).relative_to(root).as_posix())
    return frozenset(entries)


def created(before: frozenset[str] | None, after: frozenset[str] | None) -> list[str]:
    """What appeared between two snapshots; ``"."`` when the dir itself did."""
    if after is None:
        return []
    if before is None:
        return [".", *sorted(after)]
    return sorted(after - before)
