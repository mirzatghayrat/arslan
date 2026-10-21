"""S3a: a turn's first change saves the working folder as it was, once (card S3; ⓪Plan's Q1/Q3).

Before S3 nothing kept the OLD contents: `_snapshot_write` stores what was written, as a deliverable.
Now the first write_file, edit_file or run_command of a run saves the working folder first: per-file
clones on APFS (`clonefile`, almost no space), a plain copy elsewhere (Linux CI, other filesystems).
- Once per run: a later change in the same run saves nothing more; the earliest copy is the one undo uses.
- Folders that can be rebuilt (node_modules, .venv, build, …) are left out and listed; `.git` is kept.
- Never followed or copied: a symlinked folder, a FIFO, a socket or a device (a FIFO once froze the backend).
- Arslan's own data folder is never copied, even when the working folder contains it (a folder of `~`).
- Too many files or too little disk: nothing is saved, and the manifest says why; so does another volume.
- When the run ends, `finish` records how it left every path it changed, and the saved copy's sha256 for
  each, so a restore can tell a copy someone changed afterwards (Q3).
"""
import hashlib
import os
import sys

import pytest

from server import config
from server.services import checkpoints


@pytest.fixture
def ws(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: data)
    work = tmp_path / "work"
    work.mkdir()
    (work / "notes.md").write_text("before")
    (work / "sub").mkdir()
    (work / "sub" / "a.txt").write_text("a")
    (work / "node_modules").mkdir()
    (work / "node_modules" / "big.js").write_text("x" * 10)
    (work / ".git").mkdir()
    (work / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    checkpoints._reset_for_tests()
    yield work
    checkpoints._reset_for_tests()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def test_the_first_change_saves_the_folder_as_it_was_and_only_once(ws):
    await checkpoints.ensure(7, [ws])
    (ws / "notes.md").write_text("after")
    await checkpoints.ensure(7, [ws])                            # a second change in the same run
    clone = checkpoints.clone_of(7, ws)
    assert (clone / "notes.md").read_text() == "before"
    assert (clone / "sub" / "a.txt").read_text() == "a" and (clone / ".git" / "HEAD").exists()
    assert not (clone / "node_modules").exists()
    [root] = checkpoints.manifest(7)["roots"]
    assert root["skipped"] is None and "node_modules" in root["excluded"]


async def test_folders_are_saved_too_even_empty_ones(ws):
    (ws / "empty" / "inner").mkdir(parents=True)
    await checkpoints.ensure(16, [ws])
    clone = checkpoints.clone_of(16, ws)
    assert (clone / "empty" / "inner").is_dir() and not (clone / "node_modules").exists()


async def test_a_copy_left_under_the_same_run_id_is_never_taken_for_this_runs(ws):
    await checkpoints.ensure(17, [ws])
    await checkpoints.finish(17)
    (ws / "notes.md").write_text("later")
    await checkpoints.ensure(17, [ws])                           # the id again: a database made anew
    assert (checkpoints.clone_of(17, ws) / "notes.md").read_text() == "later"
    assert checkpoints.manifest(17)["roots"][0]["finished"] is None


async def test_finish_leaves_a_copy_this_process_did_not_make_alone(ws):
    await checkpoints.ensure(18, [ws])
    await checkpoints.finish(18)
    before = checkpoints.manifest(18)
    (ws / "notes.md").write_text("changed by someone else, later")
    await checkpoints.finish(18)                                 # a later run with the same id that saved nothing
    assert checkpoints.manifest(18) == before


async def test_no_run_saves_nothing(ws):
    await checkpoints.ensure(None, [ws])
    assert checkpoints.manifest(None) is None and not checkpoints.root_dir().exists()


async def test_links_fifos_and_sockets_are_never_followed_or_opened(ws, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s")
    os.symlink(outside, ws / "linked")
    os.mkfifo(ws / "pipe")
    await checkpoints.ensure(11, [ws])                           # returns: a FIFO open would hang here
    clone = checkpoints.clone_of(11, ws)
    assert not (clone / "linked" / "secret.txt").exists() and not (clone / "pipe").exists()
    skipped = checkpoints.manifest(11)["roots"][0]["not_regular"]
    assert "pipe" in skipped and "linked" in skipped


async def test_arslans_own_data_inside_the_folder_is_never_copied(tmp_path, monkeypatch):
    work = tmp_path / "home"
    data = work / "Library" / "Arslan"
    data.mkdir(parents=True)
    (data / "arslan.db").write_text("private")
    (work / "a.txt").write_text("a")
    monkeypatch.setattr(config, "data_dir", lambda: data)
    checkpoints._reset_for_tests()
    await checkpoints.ensure(12, [work])
    clone = checkpoints.clone_of(12, work)
    assert (clone / "a.txt").exists() and not (clone / "Library" / "Arslan").exists()


async def test_a_folder_too_big_is_not_saved_and_says_so(ws, monkeypatch):
    monkeypatch.setattr(checkpoints, "MAX_FILES", 2)
    await checkpoints.ensure(8, [ws])
    [root] = checkpoints.manifest(8)["roots"]
    assert root["skipped"] == "too_large" and checkpoints.clone_of(8, ws) is None


async def test_too_little_disk_is_not_saved_and_says_so(ws, monkeypatch):
    monkeypatch.setattr(checkpoints, "_free_bytes", lambda path: 1024)
    await checkpoints.ensure(13, [ws])
    assert checkpoints.manifest(13)["roots"][0]["skipped"] == "low_disk"


async def test_a_folder_on_another_volume_is_not_saved(ws, monkeypatch):
    monkeypatch.setattr(checkpoints, "_same_volume", lambda a, b: False)
    await checkpoints.ensure(9, [ws])
    assert checkpoints.manifest(9)["roots"][0]["skipped"] == "other_volume"


async def test_the_copy_lives_in_arslans_data_folder(ws):
    await checkpoints.ensure(14, [ws])
    assert checkpoints.root_dir().resolve().is_relative_to(config.data_dir().resolve())


async def test_finish_records_how_the_run_left_each_path_and_the_copys_hash(ws):
    await checkpoints.ensure(10, [ws])
    (ws / "notes.md").write_text("after")
    (ws / "new.txt").write_text("new")
    (ws / "sub" / "a.txt").unlink()
    (ws / "node_modules" / "big.js").write_text("changed")       # left out: not tracked
    await checkpoints.finish(10)
    [root] = checkpoints.manifest(10)["roots"]
    left = root["finished"]
    assert set(left) == {"notes.md", "new.txt", "sub/a.txt"}
    assert left["sub/a.txt"]["now"] is None                      # deleted by the run
    assert left["new.txt"]["now"]["sha256"] == _sha("new") and left["new.txt"]["saved"] is None
    assert left["notes.md"]["saved"] == _sha("before") and left["notes.md"]["now"]["sha256"] == _sha("after")


async def test_finish_without_a_save_does_nothing(ws):
    await checkpoints.finish(99)
    assert checkpoints.manifest(99) is None


@pytest.mark.macos
@pytest.mark.skipif(sys.platform != "darwin", reason="clonefile is macOS")
async def test_on_a_mac_the_copy_is_a_clone_and_backups_skip_it(ws):
    await checkpoints.ensure(15, [ws])
    assert checkpoints.manifest(15)["roots"][0]["method"] == "clonefile"
    import subprocess
    out = subprocess.run(["xattr", "-p", "com.apple.metadata:com_apple_backup_excludeItem",
                          str(checkpoints.root_dir())], capture_output=True, text=True)
    assert out.returncode == 0
