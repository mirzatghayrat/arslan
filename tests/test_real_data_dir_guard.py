"""The guard that keeps tests out of the user's real data dir (tests/real_data_dir_guard.py).

Driven on temp dirs: a guard that never fires looks exactly like one that works, so
each case builds the leak it must catch — the exact trees found on 2026-10-03 — and
the cases it must ignore.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import real_data_dir_guard as guard

REPO = Path(__file__).resolve().parents[1]


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


# ── HOME and the user's ~/Arslan folder ──────────────────────────────────────────

def test_a_file_written_deep_in_the_users_folder_is_reported(tmp_path):
    _leak(tmp_path, "reports/2026", "notes")
    (tmp_path / "notes" / "todo.md").write_text("mine")
    before = guard.workspace_snapshot(tmp_path)
    (tmp_path / "reports" / "2026" / "leaked.md").write_text("from a test")
    (tmp_path / "notes" / ".DS_Store").write_bytes(b"")          # Finder, not a test
    assert guard.created(before, guard.workspace_snapshot(tmp_path)) == ["reports/2026/leaked.md"]


def test_a_users_folder_that_appears_is_reported(tmp_path):
    root = tmp_path / "Arslan"
    before = guard.workspace_snapshot(root)
    assert before is None
    _leak(root, "outputs")
    assert guard.created(before, guard.workspace_snapshot(root)) == [".", "outputs"]


def test_the_suite_runs_with_a_home_of_its_own(monkeypatch):
    """What a test that fakes sys.frozen gets: default_workspace() ignores the override and
    falls back to Path.home() / "Arslan", which is now under this session's own HOME."""
    from server.services import settings_service

    home = Path.home().resolve()
    assert home != guard.REAL_HOME and guard.inside(home, guard.SUITE_HOMES)
    monkeypatch.delenv("ARSLAN_DEFAULT_WORKSPACE", raising=False)
    workspace = settings_service.default_workspace().resolve()
    assert workspace == home / "Arslan" and workspace != guard.REAL_WORKSPACE_DIR
    assert guard.REAL_WORKSPACE_DIR == guard.REAL_HOME / "Arslan"


_INNER = '''import os
from pathlib import Path


def test_writes():
    root = Path(os.environ["INNER_REAL_ARSLAN"]) if {by_another_route} else Path.home() / "Arslan"
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "leaked.md").write_text("from a test")
'''


def _inner_run(tmp_path, *, by_another_route: bool = False, body: str | None = None,
               env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """A real pytest session under the suite's root conftest, started with HOME at a temp
    dir standing in for the user's home (``home/Arslan`` holds the user's ``mine.md``) and,
    unless ``env_extra`` hands one over, none of this run's session-home variables."""
    home = tmp_path / "home"
    (home / "Arslan" / "reports").mkdir(parents=True)
    (home / "Arslan" / "reports" / "mine.md").write_text("the user's")
    test_file = tmp_path / "test_inner.py"
    test_file.write_text(body or _INNER.format(by_another_route=by_another_route))
    env = {**os.environ, "HOME": str(home), "INNER_REAL_ARSLAN": str(home / "Arslan")}
    for key in ("PYTEST_XDIST_WORKER", guard.SUITE_HOME_ENV, guard.REAL_HOME_ENV):
        env.pop(key, None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-p", "tests.conftest", "-q",
         "-p", "no:cacheprovider", "--rootdir", str(REPO), "-c", str(REPO / "pyproject.toml")],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=180)


def test_a_test_writing_into_home_arslan_lands_in_the_suites_home(tmp_path):
    run = _inner_run(tmp_path, by_another_route=False)
    out = run.stdout + run.stderr
    assert run.returncode == 0, out
    users = tmp_path / "home" / "Arslan" / "reports"
    assert sorted(p.name for p in users.iterdir()) == ["mine.md"], out   # the real folder: untouched
    assert "the user's Arslan folder changed" not in out, out
    homes = tmp_path / "home" / guard.SUITE_HOMES.name
    assert not homes.exists() or not any(homes.iterdir())                 # the session's HOME is gone


def test_a_write_into_the_real_folder_is_reported_and_does_not_fail_the_run(tmp_path):
    """Another route into the real folder (the app, another process): reported at the end
    of the run, never a failure, and nothing removed."""
    run = _inner_run(tmp_path, by_another_route=True)
    out = run.stdout + run.stderr
    assert run.returncode == 0, out
    assert "the user's Arslan folder changed during this run" in out, out
    assert "reports/leaked.md" in out and "mine.md" not in out, out
    assert (tmp_path / "home" / "Arslan" / "reports" / "leaked.md").exists()


def test_a_killed_runs_session_home_is_swept_once_it_is_a_day_old(tmp_path):
    for name, age in (("session-old", 2 * 86_400), ("session-live", 60), ("not-ours", 2 * 86_400)):
        (tmp_path / name / "Arslan").mkdir(parents=True)
        os.utime(tmp_path / name, (os.path.getatime(tmp_path), os.path.getmtime(tmp_path) - age))
    assert guard.sweep_stale_homes(tmp_path) == ["session-old"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["not-ours", "session-live"]


def test_a_worker_takes_the_session_home_it_inherits_and_leaves_it_to_its_owner(tmp_path):
    """What an xdist worker gets: its controller's session home, so every worker resolves
    the same Path.home() (test ids carry it) and collects the same tests; and it does not
    remove a home it did not make."""
    session = tmp_path / "home" / guard.SUITE_HOMES.name / "session-controller"
    session.mkdir(parents=True)
    body = (f"from pathlib import Path\n\ndef test_home():\n"
            f"    assert Path.home() == Path({str(session.resolve())!r})\n")
    run = _inner_run(tmp_path, body=body, env_extra={
        guard.SUITE_HOME_ENV: str(session), guard.REAL_HOME_ENV: str(tmp_path / "home")})
    assert run.returncode == 0, run.stdout + run.stderr
    assert session.is_dir()
    assert [p.name for p in session.parent.iterdir()] == ["session-controller"]   # made no other
