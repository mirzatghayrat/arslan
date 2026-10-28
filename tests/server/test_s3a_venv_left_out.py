"""M3 #8 (user's trial, 10-26): a Python environment is left out of a turn's checkpoint, whatever its name.

On the user's Mac an environment Arslan made, not named venv or .venv, held 29,164 of the working folder's
35,119 files. The folder was over MAX_FILES, so nothing was saved and "Undo this turn" could not undo
anything. A folder holding `pyvenv.cfg` (PEP 405) is now left out like node_modules, by one rule everywhere:
- the count and the copy leave it out, and the manifest records it (`marked`);
- `finish` leaves out the same folders on both sides, also when the run deleted the marker, so its files are
  never taken for files the run made; one the run made is left out and listed too;
- a folder that was saved stays undoable when the run makes it an environment (`python -m venv` in a
  project), its `.git` too (⓪Plan's review: a marker found later never cancels a saved folder's undo);
- a restore never trashes, writes or makes or removes folders in one, except a file write_file saved on its own;
- write_file and edit_file under one save that file on its own, as under node_modules;
- the marker is never read through a link, a linked environment is never followed, and inside `.git`
  nothing is left out.
"""
import os
from pathlib import Path

import pytest

from server import config
from server.registry import file_tools
from server.services import checkpoints, execution_context
from tests.server.test_file_tools import ws as file_ws  # noqa: F401 — the workspace fixture of file_tools


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
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")      # the Trash restore moves into
    work = tmp_path / "work"
    work.mkdir()
    (work / "notes.md").write_text("before")
    env = work / "tools-env"                                   # not venv, not .venv: found by its marker
    (env / "lib" / "site").mkdir(parents=True)
    (env / "pyvenv.cfg").write_text("home = /usr/bin\n")
    for i in range(6):
        (env / "lib" / "site" / f"m{i}.py").write_text(f"m{i}")
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


async def test_an_environment_of_any_name_is_left_out_of_the_copy_and_recorded(ws):
    await checkpoints.ensure(1, [ws])
    clone = checkpoints.clone_of(1, ws)
    assert (clone / "notes.md").read_text() == "before" and not (clone / "tools-env").exists()
    [root] = checkpoints.manifest(1)["roots"]
    assert root["marked"] == ["tools-env"] and "tools-env" in root["excluded"]


async def test_a_folder_too_large_only_because_of_an_environment_now_saves(ws, monkeypatch):
    monkeypatch.setattr(checkpoints, "MAX_FILES", 3)            # the environment alone has 7 files
    await checkpoints.ensure(2, [ws])
    [root] = checkpoints.manifest(2)["roots"]
    assert root["skipped"] is None and (checkpoints.clone_of(2, ws) / "notes.md").exists()


async def test_restore_leaves_the_environment_exactly_as_the_run_left_it(ws, tmp_path):
    site = ws / "tools-env" / "lib" / "site"

    def change():
        (ws / "notes.md").write_text("after")
        (site / "m0.py").write_text("changed by the run")
        (site / "made.py").write_text("made by the run")
        (site / "m1.py").unlink()
    await _run(3, ws, change)
    finished = checkpoints.manifest(3)["roots"][0]["finished"]
    assert list(finished) == ["notes.md"]
    out = await checkpoints.restore_files(3)
    assert (ws / "notes.md").read_text() == "before"
    assert (site / "m0.py").read_text() == "changed by the run" and (site / "made.py").exists()
    assert not (site / "m1.py").exists() and _trash(tmp_path) == []
    assert out["runs"][0]["restored"] == ["notes.md"] and out["runs"][0]["failed"] == []


async def test_a_run_that_deletes_the_marker_does_not_make_the_environment_its_own(ws, tmp_path):
    def change():
        (ws / "tools-env" / "pyvenv.cfg").unlink()
        (ws / "notes.md").write_text("after")
    await _run(4, ws, change)
    finished = checkpoints.manifest(4)["roots"][0]["finished"]
    assert not any(rel.startswith("tools-env/") for rel in finished)
    await checkpoints.restore_files(4)
    assert len(list((ws / "tools-env" / "lib" / "site").iterdir())) == 6 and _trash(tmp_path) == []


async def test_an_environment_the_run_makes_is_left_out_and_never_trashed(ws, tmp_path):
    def change():
        new = ws / "made-env"
        (new / "lib").mkdir(parents=True)
        (new / "pyvenv.cfg").write_text("home = /usr/bin\n")
        (new / "lib" / "x.py").write_text("x")
    await _run(5, ws, change)
    [root] = checkpoints.manifest(5)["roots"]
    assert not any(rel.startswith("made-env") for rel in root["finished"]) and "made-env" not in root["folders_made"]
    assert "made-env" in root["excluded"] and "made-env" in root["marked"]          # the undo window lists it
    await checkpoints.restore_files(5)
    assert (ws / "made-env" / "lib" / "x.py").exists() and _trash(tmp_path) == []


async def test_a_saved_project_the_run_makes_an_environment_stays_undoable(ws, tmp_path):
    """`python -m venv` in a project during the run: the project was saved, so its files and its own `.git`
    still go back; only what the run made (the marker) goes to the Trash."""
    proj = ws / "proj"
    (proj / "pkg").mkdir(parents=True)
    (proj / "pkg" / "a.py").write_text("a")
    (proj / ".git").mkdir()
    (proj / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

    def change():
        (proj / "pyvenv.cfg").write_text("home = /usr/bin\n")
        (proj / "pkg" / "a.py").write_text("changed")
        (proj / ".git" / "HEAD").write_text("ref: refs/heads/other\n")
    await _run(6, ws, change)
    [root] = checkpoints.manifest(6)["roots"]
    assert {"proj/pkg/a.py", "proj/.git/HEAD", "proj/pyvenv.cfg"} <= set(root["finished"]) and "proj" not in root["marked"]
    out = await checkpoints.restore_files(6)
    assert (proj / "pkg" / "a.py").read_text() == "a"
    assert (proj / ".git" / "HEAD").read_text() == "ref: refs/heads/main\n"
    assert not (proj / "pyvenv.cfg").exists() and out["runs"][0]["failed"] == []


async def test_the_working_folder_itself_made_an_environment_stays_undoable(ws):
    (ws / ".git").mkdir()
    (ws / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

    def change():
        (ws / "pyvenv.cfg").write_text("home = /usr/bin\n")
        (ws / "notes.md").write_text("after")
        (ws / ".git" / "HEAD").write_text("ref: refs/heads/other\n")
    await _run(12, ws, change)
    out = await checkpoints.restore_files(12)
    assert (ws / "notes.md").read_text() == "before" and out["runs"][0]["git"] == "restored"
    assert (ws / ".git" / "HEAD").read_text() == "ref: refs/heads/main\n"


async def test_a_git_folder_holding_the_marker_is_never_left_out(ws):
    (ws / ".git").mkdir()
    (ws / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (ws / ".git" / "pyvenv.cfg").write_text("odd but possible\n")
    await checkpoints.ensure(13, [ws])
    [root] = checkpoints.manifest(13)["roots"]
    assert ".git" not in root["marked"] and ".git" not in root["excluded"]
    assert (checkpoints.clone_of(13, ws) / ".git" / "HEAD").read_text() == "ref: refs/heads/main\n"


async def test_a_marker_that_is_a_link_is_not_one(ws):
    (ws / "fake").mkdir()
    (ws / "fake" / "code.py").write_text("c")
    (ws / "fake" / "pyvenv.cfg").symlink_to(ws / "notes.md")
    await checkpoints.ensure(7, [ws])
    [root] = checkpoints.manifest(7)["roots"]
    assert root["marked"] == ["tools-env"] and "fake/pyvenv.cfg" in root["not_regular"]
    assert (checkpoints.clone_of(7, ws) / "fake" / "code.py").read_text() == "c"


async def test_a_linked_environment_is_never_followed(ws, tmp_path):
    outside = tmp_path / "outside-env"
    outside.mkdir()
    (outside / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (ws / "linked-env").symlink_to(outside, target_is_directory=True)
    await checkpoints.ensure(8, [ws])
    [root] = checkpoints.manifest(8)["roots"]
    assert "linked-env" in root["not_regular"] and "linked-env" not in root["marked"]
    assert not (checkpoints.clone_of(8, ws) / "linked-env").exists()


def test_the_marker_is_never_looked_up_through_a_link(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    real_env = tmp_path / "env"
    real_env.mkdir()
    (real_env / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (root / "via-link").symlink_to(real_env, target_is_directory=True)
    assert checkpoints._marked(real_env) is True
    assert checkpoints._marked_at(root.resolve(), "via-link") is False
    assert checkpoints._left_out(("via-link", "x.py"), root.resolve()) is False


async def test_inside_git_a_marker_leaves_nothing_out(ws):
    (ws / ".git" / "hooks").mkdir(parents=True)
    (ws / ".git" / "hooks" / "pyvenv.cfg").write_text("odd but possible\n")
    (ws / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\n")
    await checkpoints.ensure(9, [ws])
    clone = checkpoints.clone_of(9, ws)
    assert (clone / ".git" / "hooks" / "pre-commit").exists()
    assert checkpoints.manifest(9)["roots"][0]["marked"] == ["tools-env"]


async def test_a_restore_never_makes_or_removes_folders_in_an_environment_a_manifest_names(ws):
    (ws / "tools-env" / "empty").mkdir()
    await _run(14, ws, lambda: (ws / "notes.md").write_text("after"))
    data = checkpoints.manifest(14)
    data["roots"][0]["folders_removed"].append("tools-env/brought-back")
    data["roots"][0]["folders_made"].append("tools-env/empty")
    checkpoints._save(14, data)
    await checkpoints.restore_files(14)
    assert not (ws / "tools-env" / "brought-back").exists() and (ws / "tools-env" / "empty").is_dir()


async def test_a_file_written_in_an_environment_the_run_made_keeps_the_rest_of_it(ws, tmp_path):
    """The run makes an environment, then write_file changes a file in it: that one file goes back, and the
    environment is recorded at that write, so the rest of it is never trashed."""
    await checkpoints.ensure(15, [ws])
    new = ws / "made-env"
    (new / "lib").mkdir(parents=True)
    (new / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (new / "lib" / "keep.py").write_text("keep")
    (new / "lib" / "edit.py").write_text("before the edit")
    await checkpoints.ensure(15, [ws], written=new / "lib" / "edit.py")
    (new / "lib" / "edit.py").write_text("after the edit")
    await checkpoints.finish(15)
    [root] = checkpoints.manifest(15)["roots"]
    assert "made-env" in root["marked"] and root["written"] == ["made-env/lib/edit.py"]
    await checkpoints.restore_files(15)
    assert (new / "lib" / "edit.py").read_text() == "before the edit"
    assert (new / "lib" / "keep.py").exists() and (new / "pyvenv.cfg").exists() and _trash(tmp_path) == []


def test_what_a_plain_copy_holds_counts_a_file_saved_on_its_own_once(ws):
    """`_own_bytes` for a plain copy (no clonefile): every file of the copy once; one write_file saved in an
    environment lives there too, and is not counted twice."""
    import asyncio
    asyncio.run(checkpoints.ensure(16, [ws]))
    asyncio.run(checkpoints.ensure(16, [ws], written=ws / "tools-env" / "lib" / "site" / "m3.py"))
    data = checkpoints.manifest(16)
    data["roots"][0]["method"] = "copy"
    clone = checkpoints._run_dir(16) / data["roots"][0]["clone"]
    every = sum(os.lstat(os.path.join(top, name)).st_size for top, _, names in os.walk(clone) for name in names)
    assert checkpoints._own_bytes(16, data) == every > 0


async def test_a_restore_never_writes_into_an_environment_a_manifest_names(ws, tmp_path):
    """`finish` lists no path in a left-out folder; one there comes from a manifest written since (a command
    outside the sandbox can write it). The file is left as it is and listed as not saved."""
    await _run(10, ws, lambda: (ws / "notes.md").write_text("after"))
    data = checkpoints.manifest(10)
    target = ws / "tools-env" / "lib" / "site" / "m2.py"
    data["roots"][0]["finished"]["tools-env/lib/site/m2.py"] = {"now": checkpoints._fingerprint(target),
                                                                "saved": None}
    checkpoints._save(10, data)
    out = await checkpoints.restore_files(10)
    assert target.read_text() == "m2" and _trash(tmp_path) == []
    assert "tools-env/lib/site/m2.py" in out["runs"][0]["not_saved"]


@pytest.fixture
def env_ws(file_ws, tmp_path, monkeypatch):  # noqa: F811 — the file tools' workspace, with an environment in it
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "data_dir", lambda: data)
    env = file_ws / "tools-env"
    (env / "lib").mkdir(parents=True)
    (env / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (env / "lib" / "mod.py").write_text("old")
    checkpoints._reset_for_tests()
    yield file_ws
    checkpoints._reset_for_tests()


async def test_a_file_written_in_an_environment_is_saved_on_its_own_and_put_back(env_ws):
    with execution_context.bind_run(11):
        edited = await file_tools.EditFileExecutor().execute({"path": "tools-env/lib/mod.py", "old_string": "old",
                                                             "new_string": "new"})
    assert edited["ok"] is True
    [root] = checkpoints.manifest(11)["roots"]
    assert root["written"] == ["tools-env/lib/mod.py"]
    assert (checkpoints.clone_of(11, env_ws) / "tools-env" / "lib" / "mod.py").read_text() == "old"
    await checkpoints.finish(11)
    await checkpoints.restore_files(11)
    assert (env_ws / "tools-env" / "lib" / "mod.py").read_text() == "old"
