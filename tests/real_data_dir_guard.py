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
import tempfile
from pathlib import Path

from server.profile_paths import default_data_dir

# Resolved when the root conftest imports this module: before any test can patch
# HOME, sys.platform, XDG_DATA_HOME or APPDATA.
REAL_DATA_DIR = default_data_dir().resolve()

SUITE_DATA_DIR_PREFIX = "arslan-pytest-data-"

# Created and removed by the packaged app's own SQLite connections.
_APP_SIDECARS = frozenset({"arslan.db-wal", "arslan.db-shm", "arslan.db-journal"})
_WATCHED_TREES = ("spawns",)


PINNED_KEYS = ("ARSLAN_DATA_DIR", "ARSLAN_DB_PATH", "ARSLAN_SPAWNS_DIR")
_pinned: dict[str, str | None] = {}


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


def created(before: frozenset[str] | None, after: frozenset[str] | None) -> list[str]:
    """What appeared between two snapshots; ``"."`` when the dir itself did."""
    if after is None:
        return []
    if before is None:
        return [".", *sorted(after)]
    return sorted(after - before)
