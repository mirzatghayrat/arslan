"""The green-ring READ boundary (spec 2026-08-24 default-read).

macOS does NOT gate Desktop/Documents/Downloads for this app class — measured,
not assumed (arslan-tcc-packaged-probe). So THIS code is the entire boundary,
which is why the discriminating cases below matter more than usual: a real path
in a real green folder must resolve, and a path one step outside must not, and
the difference cannot rest on the OS refusing.
"""
import os

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import server.db.session as db_session
from server.db.models import Base, Setting

from server.services.workspace_paths import (
    PathEscape,
    SecretFile,
    green_roots,
    read_roots,
    resolve_for_read,
)


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """A HOME with the three folders, so tests never touch the real Desktop."""
    for name in ("Desktop", "Documents", "Downloads"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr("server.services.workspace_paths._home", lambda: tmp_path)
    return tmp_path


# ── which roots exist ──────────────────────────────────────────────────────────

def test_green_roots_are_the_three_folders(fake_home):
    got = {p.name for p in green_roots()}
    assert got == {"Desktop", "Documents", "Downloads"}


def test_a_missing_folder_is_absent_not_an_error(fake_home):
    (fake_home / "Downloads").rmdir()
    got = {p.name for p in green_roots()}
    assert got == {"Desktop", "Documents"}      # no throw, just fewer


def test_default_read_off_means_no_green_roots(fake_home):
    assert read_roots(None, default_read=False) == []


def test_workspace_is_added_and_survives_default_off(fake_home, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    roots = read_roots(ws, default_read=False)
    assert roots == [ws.resolve()]              # workspace alone, green off


def test_a_workspace_equal_to_a_green_folder_is_not_doubled(fake_home):
    docs = fake_home / "Documents"
    roots = read_roots(docs, default_read=True)
    assert roots.count(docs.resolve()) == 1


# ── the boundary ───────────────────────────────────────────────────────────────

def test_a_file_in_a_green_folder_resolves(fake_home):
    f = fake_home / "Desktop" / "notes.txt"
    f.write_text("hi")
    roots = read_roots(None, default_read=True)
    assert resolve_for_read(str(f), roots) == f.resolve()


def test_tilde_paths_expand(fake_home):
    (fake_home / "Desktop" / "notes.txt").write_text("hi")
    monkey = os.environ.get("HOME")
    # expanduser uses $HOME; point it at the fake home for this assertion only.
    os.environ["HOME"] = str(fake_home)
    try:
        roots = read_roots(None, default_read=True)
        got = resolve_for_read("~/Desktop/notes.txt", roots)
        assert got == (fake_home / "Desktop" / "notes.txt").resolve()
    finally:
        if monkey is not None:
            os.environ["HOME"] = monkey


def test_a_path_outside_every_root_is_refused(fake_home, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "x.txt").write_text("x")
    roots = read_roots(None, default_read=True)
    with pytest.raises(PathEscape):
        resolve_for_read(str(outside / "x.txt"), roots)


def test_ssh_is_outside_the_green_ring(fake_home):
    ssh = fake_home / ".ssh"
    ssh.mkdir()
    (ssh / "id_rsa").write_text("KEY")
    roots = read_roots(None, default_read=True)
    with pytest.raises(PathEscape):
        # ~/.ssh is NOT one of the three folders — must not be reachable by default.
        resolve_for_read(str(ssh / "config"), roots)


def test_a_secret_named_file_inside_a_green_folder_is_still_refused(fake_home):
    env = fake_home / "Desktop" / ".env"
    env.write_text("OPENAI_KEY=sk-real")
    roots = read_roots(None, default_read=True)
    with pytest.raises(SecretFile):
        resolve_for_read(str(env), roots)


def test_a_symlink_pointing_out_of_the_ring_is_refused(fake_home, tmp_path):
    secret = tmp_path / "outside-secret.txt"
    secret.write_text("s")
    link = fake_home / "Desktop" / "innocent.txt"
    link.symlink_to(secret)
    roots = read_roots(None, default_read=True)
    with pytest.raises(PathEscape):
        # realpath resolution must catch the escape, not the pretty name.
        resolve_for_read(str(link), roots)


def test_empty_roots_refuse_rather_than_allow(fake_home):
    with pytest.raises(PathEscape):
        resolve_for_read(str(fake_home / "Desktop" / "x"), [])


def test_prefix_trap_desktop_evil_does_not_pass_desktop(fake_home, tmp_path):
    # A sibling named "Desktop-evil" must not pass a "Desktop" root — the classic
    # startswith bug that _contained (is_relative_to) avoids.
    evil = fake_home / "Desktop-evil"
    evil.mkdir()
    (evil / "x.txt").write_text("x")
    roots = read_roots(None, default_read=True)
    with pytest.raises(PathEscape):
        resolve_for_read(str(evil / "x.txt"), roots)


# ── the registration behaviour the spec pins (§3.1, §3.7) ──────────────────────
# These drive the real _arslan_tools gate, not just the resolver, because the
# core value ("a novice who set nothing can read their desktop") lives there.

T0 = {"read_file", "list_dir", "search_files"}
T1 = {"write_file", "edit_file"}


async def _tools(tmp_path, monkeypatch, *, rows):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'g.db'}")
    m = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setattr("server.services.workspace_paths._home", lambda: tmp_path / "home")
    if rows:
        async with m() as s:
            for k, v in rows.items():
                s.add(Setting(key=k, value=v))
            await s.commit()
    from server.orchestrator.arslan import _arslan_tools
    keys = {t["key"] for t in await _arslan_tools()}
    await eng.dispose()
    return keys


async def test_default_ship_config_a_novice_can_read(tmp_path, monkeypatch):
    # NOTHING set — the out-of-box state. default_read defaults ON, so the read
    # trio is present with no workspace. This is the feature, as a test.
    keys = await _tools(tmp_path, monkeypatch, rows={})
    assert T0 <= keys
    assert not T1 & keys


async def test_the_switch_off_reverts_to_p1(tmp_path, monkeypatch):
    keys = await _tools(tmp_path, monkeypatch, rows={"default_read_enabled": "false"})
    assert not (T0 | T1) & keys        # no reads, no writers — exactly P1


async def test_a_workspace_alone_still_offers_everything_even_with_read_off(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    keys = await _tools(tmp_path, monkeypatch,
                        rows={"default_read_enabled": "false", "workspace_dir": str(ws)})
    assert T0 <= keys and T1 <= keys   # workspace drives both, independent of the switch


async def test_search_prunes_traversal_bombs(tmp_path, monkeypatch):
    """The skip-list is load-bearing: without it, search walks node_modules /
    Library / .git and either hangs on a real home or surfaces vendored junk. A
    match inside a pruned dir must NOT be returned
    a match in an ordinary dir
    must."""
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}")
    m = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    home = tmp_path / "home"
    desk = home / "Desktop"
    (desk / "node_modules" / "pkg").mkdir(parents=True)
    (desk / "node_modules" / "pkg" / "index.js").write_text("NEEDLE in vendored code\n")
    (desk / "real").mkdir()
    (desk / "real" / "notes.txt").write_text("NEEDLE in my own note\n")
    monkeypatch.setattr("server.services.workspace_paths._home", lambda: home)
    from server.registry import file_tools
    out = await file_tools.SearchFilesExecutor().execute({"query": "NEEDLE"})
    await eng.dispose()
    paths = [h["path"] for h in out["matches"]]
    assert any("real/notes.txt" in p for p in paths), paths
    assert not any("node_modules" in p for p in paths), paths
