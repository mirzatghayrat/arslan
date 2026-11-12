"""ASK1-a (v0.1.64; the user, 2026-11-07): "ask only for risky commands" is the default again.

- an unset policy reads ask_risky; the exact value Settings writes reads as itself; any other spelling reads ask_all;
- migration 0095 writes nothing to the policy: on an existing install whose stored policy isn't ask_risky it sets
  the one-time note (replacing a pending 0070 notice), for a stored ask_risky it clears a pending notice and sets
  none, and a new install gets none;
- the settings API sends the policy as the server reads it, which is what the window's note picks its text by;
- the gate reads the default: a harmless command in the sandbox runs with no card, a card without a sandbox, and a
  stored ask_all asks for every command;
- #406's gap (`cd <dir> && rm <relative name>` with no card) is closed by S2a-3 step 4's folder tracking (#789).

Stand-in paths only (zz-*); every database is a tmp file.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.migrations import runner
from server.db.migrations.versions import _0095_ask_risky_default_notice as m0095
from server.db.models import Base
from server.services import settings_service, storage_boot

NOTE = "shell_policy_switch_notice"


async def _boot(db_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await storage_boot.initialize(engine)
    finally:
        await engine.dispose()


def _rows(db_path) -> dict[str, str]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return dict(conn.execute(sa.text(
                "SELECT key, value FROM settings WHERE key IN ('shell_confirm_policy', :note)"), {"note": NOTE}).all())
    finally:
        engine.dispose()


def _seed(db_path, **values: str | None) -> None:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            for key, value in values.items():
                if value is not None:
                    conn.execute(sa.text("INSERT OR REPLACE INTO settings(key, value) VALUES (:k, :v)"),
                                 {"k": key, "v": value})
    finally:
        engine.dispose()


def _before_0095(db_path) -> None:
    """An existing install from before ASK1-a: every migration but 0095 recorded."""
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            Base.metadata.create_all(conn)
            runner._ensure_table(conn)
            for vid, _ in runner.MIGRATIONS:
                if vid != "0095":
                    conn.execute(sa.text("INSERT INTO schema_version(version, applied_at) VALUES (:v, 'then')"),
                                 {"v": vid})
    finally:
        engine.dispose()


async def _policy(db_path) -> str:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with async_sessionmaker(engine, class_=AsyncSession)() as session:
            return await settings_service.shell_confirm_policy(session)
    finally:
        await engine.dispose()


# ── the default ──────────────────────────────────────────────────────────────

async def test_a_new_install_asks_only_for_risky_commands(tmp_path):
    db = tmp_path / "new.db"
    await _boot(db)
    assert _rows(db) == {} and await _policy(db) == "ask_risky"


@pytest.mark.parametrize("stored, reads", [
    ("ask_risky", "ask_risky"), ("ask_all", "ask_all"),
    ("", "ask_all"), ("garbage", "ask_all"), (" ask_risky", "ask_all"),
    ("ASK_RISKY", "ask_all"), ("ask_risky" + chr(0xA0), "ask_all"), ("ask_everything", "ask_all"),   # NBSP spelled out
])
async def test_only_unset_and_the_exact_value_read_ask_risky(tmp_path, stored, reads):
    """Anything unreadable stays strict: an unknown spelling reads ask_all, and a stored ask_all stays."""
    db = tmp_path / "spelling.db"
    await _boot(db)
    _seed(db, shell_confirm_policy=stored)
    assert await _policy(db) == reads


# ── migration 0095 ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("stored, before, after", [
    ("ask_all", None, "pending"),          # kept, and told how to switch
    ("ask_all", "pending", "pending"),     # a pending 0070 notice is replaced, not shown twice
    ("ask_all", "seen", "pending"),        # 0070's notice seen in v0.1.63: this is a new note
    (None, None, "pending"),               # moves to ask_risky, and told so
    (None, "pending", "pending"),
    ("garbage", None, "pending"),          # reads ask_all: told how to switch
    (" ASK_RISKY ", None, "pending"),      # a near miss reads ask_all, so it is told too (0095 matches exactly)
    ("ask_risky\n", "pending", "pending"),
    ("ask_risky", "pending", None),        # nothing changes for it: the pending 0070 notice is cleared
    ("ask_risky", None, None),
    ("ask_risky", "seen", "seen"),         # only a pending notice is cleared
])
async def test_an_existing_install_is_told_once_and_its_policy_is_untouched(tmp_path, stored, before, after):
    db = tmp_path / "old.db"
    _before_0095(db)
    _seed(db, shell_confirm_policy=stored, **{NOTE: before})
    await _boot(db)
    rows = _rows(db)
    assert rows.get("shell_confirm_policy") == stored                 # 0095 writes nothing to the policy
    assert rows.get(NOTE) == after
    assert await _policy(db) == ("ask_risky" if stored in (None, "ask_risky") else "ask_all")


@pytest.mark.parametrize("stored", [None, "ask_all", "ask_risky"])
async def test_a_new_install_gets_no_note(tmp_path, stored):
    """create_all makes its tables this boot (runner.EXISTED_BEFORE_THIS_BOOT is false)."""
    db = tmp_path / "new.db"
    await _boot(db)
    assert _rows(db) == {}
    _seed(db, shell_confirm_policy=stored)
    await _boot(db)                                  # a restart: 0095 is recorded and never runs again
    assert NOTE not in _rows(db)


@pytest.mark.parametrize("stored, before", [
    ("ask_all", None), (None, "pending"), ("ask_risky", "pending"), ("ask_risky", "seen"), ("garbage", None)])
def test_0095_twice_leaves_the_same_rows(tmp_path, stored, before):
    db = tmp_path / "twice.db"
    _before_0095(db)
    _seed(db, shell_confirm_policy=stored, **{NOTE: before})
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            m0095.upgrade_sync(conn)                 # called on its own: an install counts as existing
            once = conn.execute(sa.text("SELECT key, value FROM settings ORDER BY key")).all()
            m0095.upgrade_sync(conn)
            twice = conn.execute(sa.text("SELECT key, value FROM settings ORDER BY key")).all()
    finally:
        engine.dispose()
    assert once == twice
    assert dict(once).get("shell_confirm_policy") == stored


@pytest.mark.parametrize("stored", [None, "ask_all"])
def test_0095_called_on_its_own_counts_the_install_as_existing(tmp_path, stored):
    """No runner marker on the connection (as 0070 reads it): the install is an existing one and gets the note."""
    db = tmp_path / "bare-call.db"
    _before_0095(db)
    _seed(db, shell_confirm_policy=stored)
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            assert runner.EXISTED_BEFORE_THIS_BOOT not in conn.info
            m0095.upgrade_sync(conn)
    finally:
        engine.dispose()
    assert _rows(db).get(NOTE) == "pending"


def test_0095_leaves_a_database_without_settings_alone(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'bare.db'}")
    try:
        with engine.begin() as conn:
            m0095.upgrade_sync(conn)
            assert conn.execute(sa.text("SELECT name FROM sqlite_master")).all() == []
    finally:
        engine.dispose()


async def test_an_install_from_before_the_ledger_counts_as_existing(tmp_path):
    db = tmp_path / "pre-ledger.db"
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            Base.metadata.create_all(conn)
    finally:
        engine.dispose()
    await _boot(db)
    assert _rows(db) == {NOTE: "pending"} and await _policy(db) == "ask_risky"


@pytest.mark.parametrize("stored, policy", [("ask_risky", "ask_all"), (None, "ask_risky")])
async def test_an_install_from_v0162_gets_one_note(tmp_path, stored, policy):
    """0070 still moves a stored ask_risky to ask_all; then 0095, not 0070, sets the one note."""
    db = tmp_path / "v0162.db"
    _before_0095(db)
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM schema_version WHERE version = '0070'"))
    finally:
        engine.dispose()
    _seed(db, shell_confirm_policy=stored)
    await _boot(db)
    assert _rows(db).get(NOTE) == "pending" and await _policy(db) == policy


async def test_the_note_once_seen_stays_seen_across_restarts(tmp_path):
    db = tmp_path / "seen.db"
    _before_0095(db)
    await _boot(db)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    try:
        async with async_sessionmaker(engine, class_=AsyncSession)() as session:
            await settings_service.update_settings(session, {NOTE: "seen"})
    finally:
        await engine.dispose()
    await _boot(db)
    await _boot(db)
    assert _rows(db).get(NOTE) == "seen"


# ── what the window reads ────────────────────────────────────────────────────

async def test_the_settings_api_sends_the_policy_as_read_and_the_note(client):
    from server.db import session as db_session
    body = (await client.get("/api/v1/settings")).json()
    assert (body["shell_confirm_policy"], body[NOTE]) == ("ask_risky", "")          # a new database: unset
    for stored, reads in (("garbage", "ask_all"), ("ask_all", "ask_all"), ("ask_risky", "ask_risky")):
        async with db_session.AsyncSessionLocal() as session:
            await settings_service.update_settings(session, {"shell_confirm_policy": stored})
        assert (await client.get("/api/v1/settings")).json()["shell_confirm_policy"] == reads
    async with db_session.AsyncSessionLocal() as session:
        await settings_service.update_settings(session, {NOTE: "pending"})
    assert (await client.get("/api/v1/settings")).json()[NOTE] == "pending"
    assert (await client.put("/api/v1/settings", json={NOTE: "seen"})).status_code == 200
    assert (await client.get("/api/v1/settings")).json()[NOTE] == "seen"


# ── the gate reads the default ───────────────────────────────────────────────

class _Exec:
    key = "run_command"

    def __init__(self):
        self.ran: list[str] = []

    async def execute(self, args):
        self.ran.append(args["command"])
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "workspace"}


async def _run(monkeypatch, command: str, *, available: bool = True) -> tuple[list, list]:
    """One run_command through the real gate, with the policy and the sandbox switch read from the tmp database."""
    from server.orchestrator import tool_loop, untrusted
    from server.orchestrator.turn_state import ToolTurn
    from server.services import command_sandbox
    ex = _Exec()
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", ex)
    monkeypatch.setattr(command_sandbox, "available", lambda: available)
    asked: list = []

    async def card(command, argv, **kw):
        asked.append(command)
        return False

    async def resolve():
        return [{"key": "run_command", "description": "run"}]
    turn = untrusted.track_turn()
    try:
        await tool_loop._run_tool("run_command", {"command": command}, "{}", ToolTurn(
            resolve_tools=resolve, emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
            confirm_command=card, conversation_id="c-ask1a"))
    finally:
        untrusted.end_turn(turn)
    return asked, ex.ran


async def test_by_default_a_harmless_command_in_the_sandbox_runs_with_no_card(execution_db, monkeypatch):
    assert await _run(monkeypatch, "ls") == ([], ["ls"])


async def test_by_default_with_no_sandbox_it_gets_a_card(execution_db, monkeypatch):
    assert await _run(monkeypatch, "ls", available=False) == (["ls"], [])


async def test_a_stored_ask_all_still_asks_for_every_command(execution_db, monkeypatch):
    async with execution_db() as session:
        await settings_service.update_settings(session, {"shell_confirm_policy": "ask_all"})
    assert await _run(monkeypatch, "ls") == (["ls"], [])


# ── #406's gap, closed by S2a-3 step 4 (#789) ───────────────────────────────

@pytest.mark.parametrize("text, verdict", [
    ("rm zz-file", ("run", "")),
    ("cd zz-inside && rm zz-file", ("run", "")),
    ("cd zz-inside; rm zz-file", ("run", "")),
    ("cd .. && rm zz-file", ("ask", "delete-outside")),
    ("cd ../zz-elsewhere && rm zz-file", ("ask", "delete-outside")),
    ("cd ~ && rm zz-file", ("ask", "delete-outside")),
    ("cd /zz-elsewhere && rm -f zz-file", ("ask", "delete-outside")),
])
def test_a_relative_delete_after_cd_is_judged_where_it_runs(tmp_path, text, verdict):
    """#406 (closed unmerged): `cd <dir> && rm <relative name>` was read against the working folder, so a delete
    elsewhere could run with no card. The folder is now followed, so it asks `delete-outside` outside the folder."""
    from server.services import terminal_policy as tp
    work = tmp_path / "zz-work"
    (work / "zz-inside").mkdir(parents=True)
    result = tp.assess(text, cwd=work)
    assert (result.level, result.rule) == verdict


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="open: command_gate.check calls terminal_policy.assess(command) with no working "
                   "folder, so #789's folder tracking never runs at the gate; in the sandbox the kernel stops the delete, "
                   "outside it (a conversation's outside grant) it runs with no card. Flips when the gate passes cwd.")
async def test_by_default_a_relative_delete_outside_the_folder_gets_its_card(execution_db, monkeypatch, tmp_path):
    work = tmp_path / "zz-work"
    work.mkdir()
    async with execution_db() as session:
        await settings_service.update_settings(session, {"workspace_dir": str(work)})
    assert await _run(monkeypatch, "cd .. && rm zz-file") == (["cd .. && rm zz-file"], [])
    assert await _run(monkeypatch, "rm zz-file") == ([], ["rm zz-file"])
