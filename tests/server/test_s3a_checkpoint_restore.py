"""S3a: putting a run's files back (card S3; ⓪Plan's Q3).

Path by path, from what `finish` recorded:
- **as the run left it** → back to how it was before the run: bytes, mode and mtime;
- **changed since** (someone else touched it) → kept and listed, never overwritten;
- **made by the run and as it left it** → to the Trash (never deleted outright);
- **a folder the run removed** comes back; **one it made** goes when it is empty;
- **`.git` whole or not at all:** back only if every file but objects is as the run left it and no
  `index.lock`; otherwise untouched and listed;
- **the saved copy is checked against the hash `finish` recorded** before it is written back (Q3);
- **no link is followed** in any folder of the path; a link swapped in fails that file only;
- **later runs on the same folder are undone first**, newest first;
- refused while a run is changing the folder, for a run that has not finished, and a second time.
"""
import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from server import config
from server.services import checkpoints

OLD_NS = 1_600_000_000_000_000_000


@pytest.fixture(autouse=True)
def _plenty_of_disk(monkeypatch):
    # What a save holds is tested here, not free space. CI's /tmp is a small tmpfs that
    # fills as the suite runs; below MIN_FREE every save in this file would be skipped as
    # low_disk. The low-disk case has its own test in test_s3a_checkpoint_save.py.
    monkeypatch.setattr(checkpoints, "_free_bytes", lambda path: 2 * checkpoints.MIN_FREE)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: data)
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    work = tmp_path / "work"
    work.mkdir()
    (work / "notes.md").write_text("before")
    os.utime(work / "notes.md", ns=(OLD_NS, OLD_NS))
    os.chmod(work / "notes.md", 0o640)
    (work / "sub").mkdir()
    (work / "sub" / "a.txt").write_text("a")
    (work / "sub" / "empty").mkdir()
    checkpoints._reset_for_tests()
    yield work.resolve()
    checkpoints._reset_for_tests()


def _trash(tmp_path) -> list[str]:
    trash = tmp_path / "home" / ".Trash"
    return sorted(p.name for p in trash.iterdir()) if trash.exists() else []


async def _run(run_id, ws, change):
    await checkpoints.ensure(run_id, [ws])
    change()
    await checkpoints.finish(run_id)


async def test_files_go_back_with_their_bytes_mode_and_mtime_and_new_ones_go_to_the_trash(ws, tmp_path):
    def change():
        (ws / "notes.md").write_text("after")
        os.chmod(ws / "notes.md", 0o600)
        (ws / "new.txt").write_text("new")
    await _run(1, ws, change)
    out = await checkpoints.restore_files(1)
    st = os.stat(ws / "notes.md")
    assert (ws / "notes.md").read_text() == "before" and st.st_mtime_ns == OLD_NS and st.st_mode & 0o777 == 0o640
    assert not (ws / "new.txt").exists() and any("new.txt" in name for name in _trash(tmp_path))
    [run] = out["runs"]
    assert run["restored"] == ["notes.md"] and run["trashed"] == ["new.txt"] and run["user_changed"] == []


async def test_a_file_changed_after_the_run_is_kept_and_listed(ws):
    await _run(2, ws, lambda: (ws / "notes.md").write_text("by the run"))
    (ws / "notes.md").write_text("by the user, later")
    out = await checkpoints.restore_files(2)
    assert (ws / "notes.md").read_text() == "by the user, later"
    assert out["runs"][0]["user_changed"] == ["notes.md"] and out["runs"][0]["restored"] == []


async def test_a_folder_the_run_removed_comes_back_as_it_was(ws):
    await _run(3, ws, lambda: shutil.rmtree(ws / "sub"))
    await checkpoints.restore_files(3)
    assert (ws / "sub" / "a.txt").read_text() == "a" and (ws / "sub" / "empty").is_dir()


async def test_a_folder_the_run_made_goes_when_empty_and_stays_when_someone_filled_it(ws):
    def change():
        (ws / "made" / "deep").mkdir(parents=True)
        (ws / "made" / "deep" / "f.txt").write_text("x")
        (ws / "kept").mkdir()
    await _run(4, ws, change)
    (ws / "kept" / "users.txt").write_text("the user's")
    await checkpoints.restore_files(4)
    assert not (ws / "made").exists() and (ws / "kept" / "users.txt").exists()


async def test_a_saved_copy_changed_since_is_never_written_back(ws):
    await _run(5, ws, lambda: (ws / "notes.md").write_text("after"))
    (checkpoints.clone_of(5, ws) / "notes.md").write_text("planted")
    out = await checkpoints.restore_files(5)
    assert (ws / "notes.md").read_text() == "after" and out["runs"][0]["failed"] == ["notes.md"]


async def test_a_link_swapped_in_at_restore_fails_that_file_and_the_outside_is_untouched(ws, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.txt").write_text("outside")
    await _run(6, ws, lambda: shutil.rmtree(ws / "sub"))
    os.symlink(outside, ws / "sub")                              # the folder is now a link out
    out = await checkpoints.restore_files(6)
    assert (outside / "a.txt").read_text() == "outside" and not (outside / "empty").exists()
    assert "sub/a.txt" in out["runs"][0]["failed"] + out["runs"][0]["user_changed"]


async def test_undoing_an_earlier_run_undoes_the_later_ones_first(ws):
    await _run(7, ws, lambda: (ws / "notes.md").write_text("seven"))
    await _run(8, ws, lambda: (ws / "notes.md").write_text("eight"))
    out = await checkpoints.restore_files(7)
    assert (ws / "notes.md").read_text() == "before"
    assert [r["run_id"] for r in out["runs"]] == [8, 7] and out["later"] == [8]


async def test_refused_while_a_run_changes_the_folder_and_both_are_listed(ws):
    await _run(9, ws, lambda: (ws / "notes.md").write_text("nine"))
    await checkpoints.ensure(10, [ws])                           # run 10 is still going
    with pytest.raises(checkpoints.Refused) as refused:
        await checkpoints.restore_files(9)
    assert refused.value.code == "running" and refused.value.runs == [10]
    assert (ws / "notes.md").read_text() == "nine"


async def test_a_first_change_waits_for_a_restore_in_progress(ws):
    checkpoints._restoring.acquire()                             # a restore is putting files back
    try:
        task = asyncio.create_task(checkpoints.ensure(18, [ws]))
        await asyncio.sleep(0.3)
        assert not task.done() and checkpoints.manifest(18) is None
    finally:
        checkpoints._restoring.release()
    await task
    assert checkpoints.manifest(18) is not None


async def test_refused_twice_and_when_nothing_was_saved(ws):
    await _run(11, ws, lambda: (ws / "notes.md").write_text("x"))
    await checkpoints.restore_files(11)
    with pytest.raises(checkpoints.Refused) as again:
        await checkpoints.restore_files(11)
    assert again.value.code == "already"
    with pytest.raises(checkpoints.Refused) as none:
        await checkpoints.restore_files(99)
    assert none.value.code == "none"


async def test_refused_for_a_run_that_never_finished(ws):
    await checkpoints.ensure(14, [ws])
    (ws / "notes.md").write_text("half done")
    checkpoints._reset_for_tests()                               # the backend stopped mid-run
    with pytest.raises(checkpoints.Refused) as refused:
        await checkpoints.restore_files(14)
    assert refused.value.code == "not_finished" and refused.value.runs == [14]
    assert (ws / "notes.md").read_text() == "half done"


async def test_a_made_file_whose_folder_became_a_link_is_not_moved(ws, tmp_path):
    def change():
        (ws / "made").mkdir()
        (ws / "made" / "x.txt").write_text("x")
    await _run(15, ws, change)
    outside = tmp_path / "outside"
    shutil.move(ws / "made", outside)                            # the same file, now outside, and a link to it
    os.symlink(outside, ws / "made")
    out = await checkpoints.restore_files(15)
    assert (outside / "x.txt").exists() and out["runs"][0]["failed"] == ["made/x.txt"]


def _git(ws, *args):
    return subprocess.run(["git", "-C", str(ws), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           "-c", "commit.gpgsign=false", *args], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(ws):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    _git(ws, "init", "-q", "-b", "main")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "-m", "first")
    _git(ws, "branch", "feature/build/x")                        # a ref folder named like a left-out one
    return ws


async def test_a_commit_the_run_made_is_undone_whole(repo):
    before = _git(repo, "log", "--oneline")

    def change():
        (repo / "notes.md").write_text("after")
        _git(repo, "commit", "-q", "-am", "by the run")
    await _run(12, repo, change)
    out = await checkpoints.restore_files(12)
    assert out["runs"][0]["git"] == "restored"
    assert _git(repo, "log", "--oneline") == before and _git(repo, "status", "--porcelain") == ""
    assert "feature/build/x" in _git(repo, "branch", "--list")
    _git(repo, "fsck", "--no-progress")


async def test_a_commit_the_user_made_afterwards_leaves_git_untouched_and_listed(repo):
    def change():
        (repo / "notes.md").write_text("after")
        _git(repo, "commit", "-q", "-am", "by the run")
    await _run(13, repo, change)
    (repo / "sub" / "a.txt").write_text("the user's")
    _git(repo, "commit", "-q", "-am", "by the user")
    after = _git(repo, "log", "--oneline")
    out = await checkpoints.restore_files(13)
    assert out["runs"][0]["git"] == "kept" and _git(repo, "log", "--oneline") == after


async def test_git_holding_its_index_is_left_alone(repo):
    def change():
        (repo / "notes.md").write_text("after")
        _git(repo, "commit", "-q", "-am", "by the run")
    await _run(16, repo, change)
    after = _git(repo, "log", "--oneline")
    (repo / ".git" / "index.lock").write_text("")                # a git command is running
    out = await checkpoints.restore_files(16)
    (repo / ".git" / "index.lock").unlink()
    assert out["runs"][0]["git"] == "kept" and _git(repo, "log", "--oneline") == after


async def test_a_saved_git_changed_since_is_never_put_back(repo):
    def change():
        (repo / "notes.md").write_text("after")
        _git(repo, "commit", "-q", "-am", "by the run")
    await _run(17, repo, change)
    saved = checkpoints.clone_of(17, repo) / ".git" / "description"
    st = os.stat(saved)
    text = saved.read_text()
    saved.write_text("planted" + text[len("planted"):])          # same size, and the mtime put back
    os.utime(saved, ns=(st.st_atime_ns, st.st_mtime_ns))
    out = await checkpoints.restore_files(17)
    assert out["runs"][0]["git"] == "kept" and not (repo / ".git" / "description").read_text().startswith("planted")
