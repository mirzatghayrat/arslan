"""The guard that keeps tests out of the user's real data dir (tests/real_data_dir_guard.py).

Driven on temp dirs: a guard that never fires looks exactly like one that works, so
each case builds the leak it must catch — the exact trees found on 2026-10-03 — and
the cases it must ignore.
"""
from __future__ import annotations

import os

import pytest

from tests import real_data_dir_guard as guard


def _leak(root, *relative):
    for rel in relative:
        (root / rel).mkdir(parents=True)


def test_an_unchanged_dir_is_clean(tmp_path):
    _leak(tmp_path, "spawns/Coding Assistant/.evolution", "tool_outputs")
    assert guard.created(guard.snapshot(tmp_path), guard.snapshot(tmp_path)) == []


def test_the_probe_folder_is_reported(tmp_path):
    (tmp_path / "arslan.db").write_bytes(b"")
    before = guard.snapshot(tmp_path)
    _leak(tmp_path, "does_not_exist_probe/spawns/S/.evolution",
          "does_not_exist_probe/spawns/S2/.evolution")
    assert guard.created(before, guard.snapshot(tmp_path)) == ["does_not_exist_probe"]


def test_a_new_spawn_under_existing_spawns_is_reported(tmp_path):
    _leak(tmp_path, "spawns/Coding Assistant/.evolution")
    before = guard.snapshot(tmp_path)
    _leak(tmp_path, "spawns/S/.evolution")
    (tmp_path / "spawns/Coding Assistant/.evolution/feedback_log.jsonl").write_text("{}\n")
    assert guard.created(before, guard.snapshot(tmp_path)) == [
        "spawns/Coding Assistant/.evolution/feedback_log.jsonl",
        "spawns/S",
        "spawns/S/.evolution",
    ]


def test_a_dir_that_did_not_exist_and_now_does_is_reported(tmp_path):
    root = tmp_path / "Arslan"
    before = guard.snapshot(root)
    assert before is None
    _leak(root, "spawns/S/.evolution")
    assert guard.created(before, guard.snapshot(root)) == [
        ".", "spawns", "spawns/S", "spawns/S/.evolution"]


def test_a_dir_that_stays_absent_is_clean(tmp_path):
    root = tmp_path / "Arslan"
    assert guard.created(guard.snapshot(root), guard.snapshot(root)) == []


def test_what_the_running_app_writes_is_not_reported(tmp_path):
    """The packaged app may be running during a test run: its SQLite sidecars come and
    go with its connections, and it writes under tool_outputs/ on its own."""
    _leak(tmp_path, "tool_outputs")
    (tmp_path / "arslan.db").write_bytes(b"")
    before = guard.snapshot(tmp_path)
    for sidecar in ("arslan.db-wal", "arslan.db-shm", "arslan.db-journal"):
        (tmp_path / sidecar).write_bytes(b"")
    (tmp_path / "tool_outputs" / "out-1.txt").write_text("x")
    assert guard.created(before, guard.snapshot(tmp_path)) == []


def test_inside(tmp_path):
    root = tmp_path / "Arslan"
    assert guard.inside(root, root)
    assert guard.inside(root / "does_not_exist_probe" / "spawns", root)
    assert guard.inside(str(root / "arslan.db"), root)
    assert not guard.inside(tmp_path / "Arslan-other", root)
    assert not guard.inside(tmp_path, root)


def test_the_suite_runs_on_a_throwaway_data_dir():
    """Whatever env pytest was started with — even ARSLAN_DATA_DIR unset, which IS the
    user's real dir — the suite's ambient data dir is the temp dir the root conftest
    pinned before any server.* import."""
    import server.config as config

    ambient = config.data_dir()
    assert ambient.name.startswith(guard.SUITE_DATA_DIR_PREFIX)
    assert not guard.inside(ambient, guard.REAL_DATA_DIR)


@pytest.mark.parametrize("key", guard.PINNED_KEYS)
def test_a_pinned_key_changed_outside_monkeypatch_is_put_back(key):
    """What packaging/server_entry._sanitize_env does to the real os.environ: pop the
    data dir. Popping a pinned-absent key is a no-op, so those get set instead."""
    before = os.environ.get(key)
    if before is None:
        os.environ[key] = "/somewhere/else"
    else:
        del os.environ[key]
    try:
        assert guard.restore_pin() == [key]
        assert os.environ.get(key) == before
        assert guard.restore_pin() == []
    finally:
        if os.environ.get(key) != before:  # only if restore_pin failed
            if before is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = before
