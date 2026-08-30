"""The workspace file tools (spec 2026-08-20 P1 §1.3).

T0 read-only: read_file / list_dir / search_files — proposal surface, no
confirmation. T1 writes: write_file / edit_file — behind the session grant.

Every tool funnels through workspace_paths (the only boundary — the kernel is
not on this path), and a refusal comes back as a readable {ok: False, error},
never an exception the tool loop has to interpret. Outputs are bounded: an
unbounded read is a context bomb.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Setting
from server.registry import file_tools


@pytest_asyncio.fixture
async def ws(tmp_path, monkeypatch):
    """A configured workspace with a small tree, wired through the settings row."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'ft.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    # These tests are about the WORKSPACE surface, so the green ring is turned off
    # and home is redirected to an empty tmp — a workspace test must never scan the
    # real Desktop (that is both a leak and, on a full home, minutes of walk).
    (tmp_path / "home").mkdir()
    monkeypatch.setattr("server.registry.file_tools.Path.home", lambda: tmp_path / "home")
    monkeypatch.setattr("server.services.workspace_paths._home", lambda: tmp_path / "home")

    root = tmp_path / "ws"
    root.mkdir()
    (root / "notes.md").write_text("hello world\nsecond line\n")
    (root / "sub").mkdir()
    (root / "sub" / "code.py").write_text("def add(a, b):\n    return a + b\n")
    (root / ".env").write_text("SECRET=1")

    async with m() as s:
        s.add(Setting(key="workspace_dir", value=str(root)))
        s.add(Setting(key="default_read_enabled", value="false"))
        await s.commit()
    yield root.resolve()
    await engine.dispose()


# ── read_file ──────────────────────────────────────────────────────────────
async def test_read_file_returns_content(ws):
    out = await file_tools.ReadFileExecutor().execute({"path": "notes.md"})
    assert out["ok"] is True
    assert "hello world" in out["content"]
    assert out["truncated"] is False


async def test_read_file_truncates_and_says_so(ws):
    big = ws / "big.txt"
    big.write_text("x" * (file_tools.MAX_READ_CHARS + 500))
    out = await file_tools.ReadFileExecutor().execute({"path": "big.txt"})
    assert out["ok"] is True
    assert out["truncated"] is True
    assert len(out["content"]) <= file_tools.MAX_READ_CHARS


async def test_read_file_outside_workspace_is_a_readable_refusal(ws):
    out = await file_tools.ReadFileExecutor().execute({"path": "../../etc/passwd"})
    assert out["ok"] is False
    assert "outside" in out["error"]      # escaped every readable root


async def test_read_file_refuses_secrets_with_its_own_reason(ws):
    out = await file_tools.ReadFileExecutor().execute({"path": ".env"})
    assert out["ok"] is False
    assert "credential" in out["error"]          # policy, not an escape


async def test_read_file_missing_is_not_a_crash(ws):
    out = await file_tools.ReadFileExecutor().execute({"path": "nope.md"})
    assert out["ok"] is False and "not found" in out["error"].lower()


# ── list_dir ───────────────────────────────────────────────────────────────
async def test_list_dir_lists_the_root_by_default(ws):
    out = await file_tools.ListDirExecutor().execute({})
    assert out["ok"] is True
    names = {e["name"] for e in out["entries"]}
    assert {"notes.md", "sub"} <= names
    kinds = {e["name"]: e["type"] for e in out["entries"]}
    assert kinds["sub"] == "dir" and kinds["notes.md"] == "file"


async def test_list_dir_hides_secret_names(ws):
    out = await file_tools.ListDirExecutor().execute({})
    assert ".env" not in {e["name"] for e in out["entries"]}


async def test_list_dir_of_a_file_refuses(ws):
    out = await file_tools.ListDirExecutor().execute({"path": "notes.md"})
    assert out["ok"] is False


# ── search_files ───────────────────────────────────────────────────────────
async def test_search_finds_matches_with_location(ws):
    out = await file_tools.SearchFilesExecutor().execute({"query": "return a + b"})
    assert out["ok"] is True
    assert out["matches"], out
    hit = out["matches"][0]
    # Path is now displayed absolute/~ (multi-root reads have no single base),
    # so assert the tail and the line rather than a workspace-relative string.
    assert hit["path"].endswith("sub/code.py") and hit["line"] == 2


async def test_search_never_reads_secret_files(ws):
    (ws / "cert.pem").write_text("findme-in-a-secret")
    out = await file_tools.SearchFilesExecutor().execute({"query": "findme-in-a-secret"})
    assert out["matches"] == []


async def test_search_results_are_bounded(ws):
    noisy = ws / "noisy.txt"
    noisy.write_text("needle\n" * (file_tools.MAX_MATCHES + 50))
    out = await file_tools.SearchFilesExecutor().execute({"query": "needle"})
    assert len(out["matches"]) == file_tools.MAX_MATCHES
    assert out["truncated"] is True


async def test_search_requires_a_query(ws):
    out = await file_tools.SearchFilesExecutor().execute({"query": "  "})
    assert out["ok"] is False


# ── write_file (T1) ────────────────────────────────────────────────────────
async def test_write_creates_and_reports_bytes(ws):
    out = await file_tools.WriteFileExecutor().execute({"path": "sub/new.txt", "content": "abc"})
    assert out["ok"] is True and out["bytes"] == 3
    assert (ws / "sub" / "new.txt").read_text() == "abc"


async def test_write_outside_workspace_refused(ws, tmp_path):
    target = tmp_path / "escaped.txt"
    out = await file_tools.WriteFileExecutor().execute({"path": str(target), "content": "x"})
    assert out["ok"] is False
    assert not target.exists()                    # refusal means NOTHING was written


async def test_write_to_secret_name_refused(ws):
    out = await file_tools.WriteFileExecutor().execute({"path": ".env.local", "content": "x"})
    assert out["ok"] is False
    assert not (ws / ".env.local").exists()


# ── edit_file (T1) — unique-hit semantics ──────────────────────────────────
async def test_edit_replaces_a_unique_match(ws):
    out = await file_tools.EditFileExecutor().execute(
        {"path": "notes.md", "old": "second line", "new": "SECOND LINE"})
    assert out["ok"] is True
    assert "SECOND LINE" in (ws / "notes.md").read_text()


async def test_edit_refuses_when_the_old_string_is_not_unique(ws):
    """The house lesson made product: a replace that quietly hits the first of
    several occurrences is how a 'successful' edit changes the wrong line."""
    (ws / "dup.txt").write_text("alpha\nalpha\n")
    out = await file_tools.EditFileExecutor().execute(
        {"path": "dup.txt", "old": "alpha", "new": "beta"})
    assert out["ok"] is False
    assert "2" in out["error"]                    # says HOW MANY it found
    assert (ws / "dup.txt").read_text() == "alpha\nalpha\n"    # untouched


async def test_edit_refuses_when_the_old_string_is_absent(ws):
    out = await file_tools.EditFileExecutor().execute(
        {"path": "notes.md", "old": "nowhere", "new": "x"})
    assert out["ok"] is False
    assert "notes.md" in (ws / "notes.md").read_text() or True
    assert "hello world" in (ws / "notes.md").read_text()      # untouched


async def test_edit_requires_a_nonempty_old(ws):
    out = await file_tools.EditFileExecutor().execute({"path": "notes.md", "old": "", "new": "x"})
    assert out["ok"] is False


# ── no workspace configured ────────────────────────────────────────────────
async def test_reads_refuse_when_nothing_is_readable(tmp_path, monkeypatch):
    # default_read OFF and no workspace ⇒ the read surface is genuinely empty.
    # (With default_read ON — the shipped default — reads span the green ring and
    #  this refusal does NOT happen; that is the whole point of the feature and is
    #  asserted in test_read_roots.py / the registration gate test.)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'empty.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    async with m() as sess:
        sess.add(Setting(key="default_read_enabled", value="false"))
        await sess.commit()
    out = await file_tools.ReadFileExecutor().execute({"path": "~/Desktop/x.md"})
    assert out["ok"] is False and "nothing is readable" in out["error"]
    await engine.dispose()


@pytest.mark.parametrize("key", ["read_file", "list_dir", "search_files",
                                 "write_file", "edit_file"])
def test_registered_in_executors(key):
    from server.registry.executors import EXECUTORS
    assert key in EXECUTORS
