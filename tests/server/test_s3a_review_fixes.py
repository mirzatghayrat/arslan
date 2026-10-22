"""S3a: ⓪Plan's security review (Opus 5.5, effort=max), the fixes.

🔴1 A write to `<left-out folder>/..` failed, but its name was recorded, and the next undo moved the whole
   working folder to the Trash (`root/".build/.."` is the root). Now every relative path is checked to stay
   inside its folder: at restore (the manifest is reachable by commands outside the sandbox: 🟠3), at save,
   and in resolve_in_workspace, which no longer accepts a `..` leaf.
🔴2 A file that existed before the run but was not saved (a copy that failed, an unreadable folder) read as
   made by the run, and undo trashed it. "Made by the run" now means absent when the folder was saved: what
   existed but was not saved is listed as not saved and never trashed.
🟡 Secret-shaped files are not copied into checkpoints (listed as not saved, so not undone); the Time Machine
   exclusion is put back when it is missing; cleanup waits for a restore; a `.git` that points elsewhere is
   reported; a restore with failures can be retried for what failed.
"""
import asyncio
import errno
import hashlib
import json
import os
import shutil
import types
from pathlib import Path

import pytest

from server import config
from server.registry import file_tools
from server.services import checkpoints, execution_context
from server.services.workspace_paths import PathEscape, resolve_in_workspace
from tests.server.test_file_tools import ws as file_ws  # noqa: F401 — the workspace fixture


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
    (work / ".build").mkdir()
    (work / "keep.txt").write_text("keep")
    checkpoints._reset_for_tests()
    yield work.resolve()
    checkpoints._reset_for_tests()


def _trash(tmp_path) -> list[str]:
    trash = tmp_path / "home" / ".Trash"
    return sorted(p.name for p in trash.iterdir()) if trash.exists() else []


def _manifest_path(run_id) -> Path:
    return checkpoints.root_dir() / str(run_id) / "manifest.json"


# ── 🔴1 / 🟠3 ─────────────────────────────────────────────────────────────────────────────────────

def test_a_dotdot_leaf_is_refused_for_writing(tmp_path):
    root = tmp_path / "w"
    (root / ".build").mkdir(parents=True)
    with pytest.raises(PathEscape):
        resolve_in_workspace(".build/..", root, for_write=True, make_parents=True)


async def test_the_reproduction_a_failed_dotdot_write_never_trashes_the_folder(file_ws, tmp_path, monkeypatch):  # noqa: F811
    data = tmp_path / "data2"
    data.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: data)
    checkpoints._reset_for_tests()
    (file_ws / ".build").mkdir()
    with execution_context.bind_run(31):
        out = await file_tools.WriteFileExecutor().execute({"path": ".build/..", "content": "x"})
        await file_tools.WriteFileExecutor().execute({"path": "notes.md", "content": "changed"})
    await checkpoints.finish(31)
    await checkpoints.restore_files(31)
    assert out["ok"] is False
    assert (file_ws / "notes.md").read_text() == "hello world\nsecond line\n" and (file_ws / "sub" / "code.py").exists()
    checkpoints._reset_for_tests()


async def test_a_dotdot_name_is_never_recorded_at_save(ws):
    await checkpoints.ensure(32, [ws], written=ws / ".build" / "..")
    assert checkpoints.manifest(32)["roots"][0]["written"] == []


@pytest.mark.parametrize("rel", [".build/..", "../outside.txt", "/etc/hosts", "sub/../../x"])
async def test_restore_trusts_no_path_from_the_manifest(ws, tmp_path, rel):
    (tmp_path / "outside.txt").write_text("outside")
    await checkpoints.ensure(33, [ws])
    await checkpoints.finish(33)
    path = _manifest_path(33)
    data = json.loads(path.read_text())
    data["roots"][0]["finished"] = {rel: {"now": checkpoints._fingerprint(ws / rel) if not rel.startswith("/")
                                          else None, "saved": None}}
    data["roots"][0]["folders_made"] = [rel]
    path.write_text(json.dumps(data))                            # a manifest a command outside the sandbox wrote
    out = await checkpoints.restore_files(33)
    assert ws.is_dir() and (ws / "notes.md").read_text() == "before" and (tmp_path / "outside.txt").exists()
    assert out["runs"][0]["failed"] == [rel] and _trash(tmp_path) == []


async def test_a_copy_folder_named_outside_the_checkpoint_is_refused(ws, tmp_path):
    await checkpoints.ensure(34, [ws])
    (ws / "notes.md").write_text("after")
    await checkpoints.finish(34)
    path = _manifest_path(34)
    data = json.loads(path.read_text())
    data["roots"][0]["clone"] = "../../elsewhere"                # <data>/elsewhere, outside checkpoints/
    planted = config.data_dir() / "elsewhere"
    planted.mkdir()
    (planted / "notes.md").write_text("planted")
    data["roots"][0]["finished"]["notes.md"]["saved"] = hashlib.sha256(b"planted").hexdigest()
    path.write_text(json.dumps(data))
    out = await checkpoints.restore_files(34)
    assert (ws / "notes.md").read_text() == "after" and out["runs"][0]["failed"] == ["notes.md"]


async def test_a_manifest_naming_arslans_own_data_folder_is_refused(ws):
    await checkpoints.ensure(43, [ws])
    (ws / "notes.md").write_text("after")
    await checkpoints.finish(43)
    path = _manifest_path(43)
    data = json.loads(path.read_text())
    data["roots"][0]["path"] = str(config.data_dir().resolve())
    path.write_text(json.dumps(data))
    out = await checkpoints.restore_files(43)
    assert out["runs"][0]["failed"] == ["notes.md"] and not (config.data_dir() / "notes.md").exists()


# ── 🔴2 ────────────────────────────────────────────────────────────────────────────────────────────

async def test_the_reproduction_a_file_that_failed_to_copy_is_never_trashed(ws, tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoints, "sys", types.SimpleNamespace(platform="linux"))   # the copy path
    monkeypatch.setattr(checkpoints, "COPY_MAX", 10)
    (ws / "big.bin").write_bytes(b"x" * 100)                      # untouched by the run
    (ws / "big2.bin").write_bytes(b"y" * 100)                     # changed by it
    await checkpoints.ensure(35, [ws])
    (ws / "notes.md").write_text("after")
    (ws / "big2.bin").write_bytes(b"z" * 200)
    await checkpoints.finish(35)
    out = await checkpoints.restore_files(35)
    assert (ws / "big.bin").exists() and (ws / "big2.bin").read_bytes() == b"z" * 200 and _trash(tmp_path) == []
    assert out["runs"][0]["not_saved"] == ["big2.bin"] and out["runs"][0]["restored"] == ["notes.md"]


def _half_then_fail(name):
    real = shutil.copy2

    def copy(src, dst, **kw):
        if str(src).endswith(name):
            with open(dst, "wb") as f:
                f.write(open(src, "rb").read()[:100])
            raise OSError(errno.ENOSPC, "No space left on device", str(dst))
        return real(src, dst, **kw)
    return copy


async def test_a_copy_that_fails_halfway_never_puts_half_a_file_back(ws, monkeypatch):
    """⓪Plan's re-check: copy2 writes the target before it can fail (ENOSPC, EIO, copystat); the partial
    file stayed in the copy, read as changed by the run, and undo wrote it over an untouched file."""
    monkeypatch.setattr(checkpoints, "sys", types.SimpleNamespace(platform="linux"))   # the copy path
    (ws / "doc.txt").write_text("the whole document, untouched by the run\n" * 50)
    whole = (ws / "doc.txt").read_text()
    monkeypatch.setattr(checkpoints.shutil, "copy2", _half_then_fail("doc.txt"))
    await checkpoints.ensure(77, [ws])
    (ws / "notes.md").write_text("after")
    await checkpoints.finish(77)
    out = await checkpoints.restore_files(77)
    assert (ws / "doc.txt").read_text() == whole and "doc.txt" not in out["runs"][0]["restored"]
    assert not any(p.name.endswith(".part") for p in checkpoints.clone_of(77, ws).iterdir())


async def test_a_left_out_file_that_fails_halfway_is_not_put_back_over_the_runs_change(ws, monkeypatch):
    monkeypatch.setattr(checkpoints, "sys", types.SimpleNamespace(platform="linux"))
    (ws / "node_modules").mkdir()
    lib = ws / "node_modules" / "lib.js"
    lib.write_text("module.exports = 1;\n" * 40)
    monkeypatch.setattr(checkpoints.shutil, "copy2", _half_then_fail("lib.js"))
    await checkpoints.ensure(78, [ws], written=lib)
    lib.write_text("changed by the run")
    await checkpoints.finish(78)
    out = await checkpoints.restore_files(78)
    assert lib.read_text() == "changed by the run" and out["runs"][0]["not_saved"] == ["node_modules/lib.js"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any folder")
async def test_a_folder_unreadable_at_save_is_never_trashed(ws, tmp_path):
    locked = ws / "locked"
    locked.mkdir()
    (locked / "old.txt").write_text("old")
    locked.chmod(0)
    try:
        await checkpoints.ensure(36, [ws])
    finally:
        locked.chmod(0o755)
    (locked / "new.txt").write_text("made later, by the run or not: unknown")
    await checkpoints.finish(36)
    out = await checkpoints.restore_files(36)
    assert (locked / "old.txt").exists() and (locked / "new.txt").exists() and _trash(tmp_path) == []
    assert set(out["runs"][0]["not_saved"]) == {"locked/old.txt", "locked/new.txt"}


# ── 🟡 ─────────────────────────────────────────────────────────────────────────────────────────────

async def test_secret_shaped_files_are_not_copied_and_never_undone(ws, tmp_path):
    (ws / ".env").write_text("TOKEN=1")
    await checkpoints.ensure(37, [ws])
    assert not (checkpoints.clone_of(37, ws) / ".env").exists()
    (ws / ".env").write_text("TOKEN=2")
    await checkpoints.finish(37)
    out = await checkpoints.restore_files(37)
    assert (ws / ".env").read_text() == "TOKEN=2" and out["runs"][0]["not_saved"] == [".env"]
    assert "TOKEN" not in _manifest_path(37).read_text()


async def test_the_backup_exclusion_is_put_back_when_missing(ws, monkeypatch):
    applied = []
    monkeypatch.setattr(checkpoints, "_tm_excluded", lambda path: False)
    monkeypatch.setattr(checkpoints, "_tm_exclude", lambda path: applied.append(path))
    await checkpoints.ensure(38, [ws])
    await checkpoints.finish(38)
    await checkpoints.ensure(39, [ws])
    assert len(applied) == 2


async def test_cleanup_waits_for_a_restore(ws):
    await checkpoints.ensure(40, [ws])
    checkpoints._restoring.acquire()
    try:
        task = asyncio.create_task(checkpoints.finish(40))
        await asyncio.sleep(0.3)
        assert not task.done()
    finally:
        checkpoints._restoring.release()
    await task


async def test_a_git_that_points_elsewhere_is_reported(ws):
    (ws / ".git").write_text("gitdir: /somewhere/else/.git/worktrees/w\n")
    await checkpoints.ensure(41, [ws])
    (ws / "notes.md").write_text("after")
    await checkpoints.finish(41)
    out = await checkpoints.restore_files(41)
    assert out["runs"][0]["git"] == "outside"


async def test_a_restore_with_failures_can_be_retried_for_what_failed(ws):
    (ws / "b.txt").write_text("b-before")
    await checkpoints.ensure(42, [ws])
    (ws / "notes.md").write_text("after")
    (ws / "b.txt").write_text("b-after")
    await checkpoints.finish(42)
    saved_b = checkpoints.clone_of(42, ws) / "b.txt"
    st = os.stat(saved_b)
    saved_b.write_text("planted!")                               # same size: only the hash tells
    os.utime(saved_b, ns=(st.st_atime_ns, st.st_mtime_ns))
    first = await checkpoints.restore_files(42)
    assert first["runs"][0]["restored"] == ["notes.md"] and first["runs"][0]["failed"] == ["b.txt"]
    saved_b.write_text("b-before")
    os.utime(saved_b, ns=(st.st_atime_ns, st.st_mtime_ns))
    second = await checkpoints.restore_files(42)
    assert second["runs"][0]["restored"] == ["b.txt"] and (ws / "b.txt").read_text() == "b-before"
    assert second["runs"][0]["user_changed"] == []                # notes.md, put back by the first try, is skipped
    assert (ws / "notes.md").read_text() == "before"
    with pytest.raises(checkpoints.Refused) as again:
        await checkpoints.restore_files(42)
    assert again.value.code == "already"


# Each layer of 🔴1(a) on its own: the restore loop checks first, so these are checked directly.
@pytest.mark.parametrize("rel", [".build/..", "../x", "/etc/hosts", "a/../../x"])
def test_the_trash_and_the_put_back_refuse_a_path_that_leaves_the_folder(ws, rel):
    with pytest.raises(ValueError):
        checkpoints._trash_inside(ws, rel)
    with pytest.raises(ValueError):
        checkpoints._put_back(ws, rel, ws / "notes.md", "0" * 64)
    assert ws.is_dir() and (ws / "notes.md").read_text() == "before"


def test_a_git_check_listing_a_path_outside_is_not_as_left(ws, tmp_path):
    (tmp_path / "x").write_text("x")
    (ws / ".git").mkdir()                                       # so the path resolves to tmp/x, and matches
    listed = {".git/../../x": {"now": checkpoints._fingerprint(tmp_path / "x"), "saved": None}}
    assert checkpoints._git_as_left(ws, ws, listed) is False
