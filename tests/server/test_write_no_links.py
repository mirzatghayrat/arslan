"""0.1.62 F4b (R1): write_file and edit_file never write outside the workspace through a link
in it: a symbolic link, a hard link, or a segment swapped for a link between the check and the
write. A stand-in for ~/.zshrc sits in the temp folder, outside the workspace."""
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Setting
from server.registry import file_tools

write = file_tools.WriteFileExecutor().execute
edit = file_tools.EditFileExecutor().execute


@pytest_asyncio.fixture
async def ws(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'ft.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    (tmp_path / "home").mkdir()
    monkeypatch.setattr("server.services.workspace_paths._home", lambda: tmp_path / "home")
    root = tmp_path / "ws"
    root.mkdir()
    async with m() as s:
        s.add(Setting(key="workspace_dir", value=str(root)))
        s.add(Setting(key="default_read_enabled", value="false"))
        await s.commit()
    yield root.resolve()
    await engine.dispose()


@pytest.fixture
def decoy(tmp_path) -> Path:
    path = tmp_path / "zshrc"
    path.write_text("export MINE=1\n")
    return path


def _outside_files(tmp_path: Path) -> set[str]:
    return {p.name for p in tmp_path.iterdir()} - {"ws", "home", "ft.db"}


# ── symbolic links ───────────────────────────────────────────────────────────────────

async def test_write_file_through_a_link_to_outside_is_refused(ws, decoy):
    (ws / "link.txt").symlink_to(decoy)
    r = await write({"path": "link.txt", "content": "pwned"})
    assert r["ok"] is False
    assert decoy.read_text() == "export MINE=1\n"


async def test_edit_file_through_a_link_to_outside_is_refused(ws, decoy):
    (ws / "link.txt").symlink_to(decoy)
    r = await edit({"path": "link.txt", "old": "MINE", "new": "PWNED"})
    assert r["ok"] is False
    assert decoy.read_text() == "export MINE=1\n"


async def test_write_file_through_a_dangling_link_creates_nothing_outside(ws, tmp_path):
    before = _outside_files(tmp_path)
    (ws / "dangling.txt").symlink_to(tmp_path / "not-yet.txt")
    r = await write({"path": "dangling.txt", "content": "pwned"})
    assert r["ok"] is False
    assert _outside_files(tmp_path) == before


async def test_write_file_through_a_link_inside_writes_its_target(ws):
    (ws / "real.txt").write_text("old")
    (ws / "alias.txt").symlink_to(ws / "real.txt")
    r = await write({"path": "alias.txt", "content": "new"})
    assert r["ok"] is True
    assert (ws / "real.txt").read_text() == "new"


async def test_a_harmless_link_name_does_not_hide_an_outside_env(ws, tmp_path):
    env = tmp_path / ".env"
    env.write_text("SECRET=1")
    (ws / "notes.txt").symlink_to(env)
    r = await write({"path": "notes.txt", "content": "pwned"})
    assert r["ok"] is False
    assert env.read_text() == "SECRET=1"


# ── hard links ───────────────────────────────────────────────────────────────────────

async def test_write_file_splits_a_hard_link_instead_of_writing_through_it(ws, decoy):
    os.link(decoy, ws / "notes.txt")
    r = await write({"path": "notes.txt", "content": "new"})
    assert r["ok"] is True
    assert decoy.read_text() == "export MINE=1\n"
    assert (ws / "notes.txt").read_text() == "new"


async def test_edit_file_splits_a_hard_link_instead_of_writing_through_it(ws, decoy):
    os.link(decoy, ws / "notes.txt")
    r = await edit({"path": "notes.txt", "old": "MINE", "new": "YOURS"})
    assert r["ok"] is True
    assert decoy.read_text() == "export MINE=1\n"
    assert (ws / "notes.txt").read_text() == "export YOURS=1\n"


# ── a segment swapped for a link after the check ─────────────────────────────────────

async def test_a_folder_swapped_for_a_link_while_it_is_made_is_caught(ws, tmp_path, monkeypatch):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    real_mkdir = Path.mkdir

    def mkdir_then_swap(self, *a, **kw):
        real_mkdir(self, *a, **kw)
        if self.name == "new":
            self.rmdir()
            self.symlink_to(outside)
    monkeypatch.setattr(Path, "mkdir", mkdir_then_swap)
    # As on a system without O_NOFOLLOW_ANY (Linux CI): the second resolve alone must catch it.
    monkeypatch.setattr(file_tools, "_NOFOLLOW", os.O_NOFOLLOW)
    r = await write({"path": "new/f.txt", "content": "pwned"})
    assert r["ok"] is False
    assert list(outside.iterdir()) == []


async def test_a_file_swapped_for_a_link_before_the_write_is_replaced_not_followed(ws, decoy, monkeypatch):
    (ws / "notes.txt").write_text("old")
    real_snapshot = file_tools._snapshot_write

    def snapshot_then_swap(root, path, content):
        out = real_snapshot(root, path, content)
        path.unlink()
        path.symlink_to(decoy)               # after the check, before the write
        return out
    monkeypatch.setattr(file_tools, "_snapshot_write", snapshot_then_swap)
    r = await write({"path": "notes.txt", "content": "new"})
    assert decoy.read_text() == "export MINE=1\n"
    if r["ok"]:
        assert not (ws / "notes.txt").is_symlink() and (ws / "notes.txt").read_text() == "new"


@pytest.mark.macos
@pytest.mark.skipif(sys.platform != "darwin", reason="O_NOFOLLOW_ANY is macOS 11+")
async def test_a_parent_swapped_for_a_link_at_the_open_is_refused_by_the_kernel(ws, tmp_path, monkeypatch):
    (ws / "sub").mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    real_open = os.open

    def swap_then_open(path, flags, *a, **kw):
        sub = ws / "sub"
        if str(path).startswith(str(sub)) and not sub.is_symlink():
            sub.rename(tmp_path / "sub-moved")
            sub.symlink_to(outside)
        return real_open(path, flags, *a, **kw)
    monkeypatch.setattr(os, "open", swap_then_open)
    r = await write({"path": "sub/f.txt", "content": "pwned"})
    assert r["ok"] is False
    assert list(outside.iterdir()) == []


# ── permissions ──────────────────────────────────────────────────────────────────────

async def test_a_new_file_is_not_executable(ws):
    r = await write({"path": "made.txt", "content": "x"})
    assert r["ok"] is True
    assert (ws / "made.txt").stat().st_mode & 0o111 == 0


async def test_overwriting_keeps_the_files_mode(ws):
    script = ws / "run.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    r = await write({"path": "run.sh", "content": "#!/bin/sh\necho hi\n"})
    assert r["ok"] is True
    assert script.stat().st_mode & 0o777 == 0o755
