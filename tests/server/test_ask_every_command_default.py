"""v0.1.63 (user's decision, after S2a-3 moved to v0.1.64): "ask before every command" is the default.

- a new install asks before every command (unset reads ask_all, and so does anything unrecognised);
- an existing user on the old default is moved to it once (migration 0070): a stored ask_risky is not taken as
  a choice, since the store keeps the value, not whether or when it was chosen;
- a choice made after that is kept, across restarts (the runner never runs 0070 again);
- the bench pins its own policy (ask_risky unless the run asks for ask_all), so its rounds stay comparable.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.migrations import runner
from server.db.migrations.versions import _0070_ask_every_command as m0070
from server.db.models import Base
from server.services import settings_service, storage_boot

#: Spellings the old, forgiving reader took as ask_risky. The reader and 0070 now share one rule, the exact
#: value Settings writes, so each of these reads ask_all before 0070 and after it (#398 review, F1).
ODD = ["ask_risky\t", "\nask_risky", "\u00a0ask_risky", "ask_risky\u3000", " ASK_RISKY ", "AS\u212a_RISKY"]


async def _boot(db_path) -> None:
    """A start, as the app's own boot prepares the database (storage_boot.initialize)."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await storage_boot.initialize(engine)
    finally:
        await engine.dispose()


def _stored(db_path) -> str | None:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return conn.execute(sa.text("SELECT value FROM settings WHERE key = 'shell_confirm_policy'")).scalar()
    finally:
        engine.dispose()


def _store(db_path, value: str) -> None:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("INSERT OR REPLACE INTO settings(key, value) VALUES ('shell_confirm_policy', :v)"),
                         {"v": value})
    finally:
        engine.dispose()


def _before_0070(db_path) -> None:
    """A database as v0.1.62 left it: every migration up to 0069 recorded."""
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            Base.metadata.create_all(conn)
            runner._ensure_table(conn)
            for vid, _ in runner.MIGRATIONS:
                if vid != "0070":
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


async def _choose(db_path, value: str) -> None:
    """The user's own choice, through the same write the Settings page makes."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with async_sessionmaker(engine, class_=AsyncSession)() as session:
            await settings_service.update_settings(session, {"shell_confirm_policy": value})
    finally:
        await engine.dispose()


async def test_a_new_install_asks_before_every_command(tmp_path):
    db = tmp_path / "new.db"
    await _boot(db)
    assert _stored(db) is None and await _policy(db) == "ask_all"
    for odd in ("", "garbage", "ask_everything"):
        _store(db, odd)
        assert await _policy(db) == "ask_all"


@pytest.mark.parametrize("stored", ["ask_risky", None])
async def test_a_user_on_the_old_default_moves_to_asking_before_every_command(tmp_path, stored):
    db = tmp_path / "old.db"
    _before_0070(db)
    if stored is not None:
        _store(db, stored)
    assert await _policy(db) == ("ask_risky" if stored else "ask_all")           # what 0070 finds
    await _boot(db)
    assert await _policy(db) == "ask_all"
    assert _stored(db) == ("ask_all" if stored else None)                         # unset stays unset


@pytest.mark.parametrize("odd", ODD)
async def test_no_other_spelling_ever_reads_as_asking_only_for_risky_commands(tmp_path, odd):
    """One rule in the reader and in 0070: a spelling 0070 does not move is one the reader never counts."""
    db = tmp_path / "odd.db"
    _before_0070(db)
    _store(db, odd)
    assert await _policy(db) == "ask_all"
    await _boot(db)
    assert await _policy(db) == "ask_all"


async def test_asking_before_every_command_chosen_before_stays(tmp_path):
    db = tmp_path / "chose-all.db"
    _before_0070(db)
    _store(db, "ask_all")
    await _boot(db)
    assert _stored(db) == "ask_all" and await _policy(db) == "ask_all"


async def test_a_choice_made_after_the_move_survives_restarts(tmp_path):
    db = tmp_path / "chose-later.db"
    _before_0070(db)
    _store(db, "ask_risky")
    await _boot(db)                                  # the move
    await _choose(db, "ask_risky")                   # chosen again, knowingly, after it
    await _boot(db)                                  # a restart …
    await _boot(db)                                  # … and another
    assert await _policy(db) == "ask_risky"


def test_0070_twice_moves_nothing_more(tmp_path):
    db = tmp_path / "twice.db"
    _before_0070(db)
    _store(db, "ask_risky")
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            m0070.upgrade_sync(conn)
            m0070.upgrade_sync(conn)
            rows = conn.execute(sa.text("SELECT key, value FROM settings")).all()
    finally:
        engine.dispose()
    assert [tuple(row) for row in rows] == [("shell_confirm_policy", "ask_all")]


def test_0070_leaves_a_database_without_settings_alone(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'bare.db'}")
    try:
        with engine.begin() as conn:
            m0070.upgrade_sync(conn)
            assert conn.execute(sa.text("SELECT name FROM sqlite_master")).all() == []
    finally:
        engine.dispose()


async def test_an_unreadable_setting_means_a_card_even_for_a_harmless_command(execution_db, monkeypatch):
    """The tool loop's own reading (tool_loop._asks_for_everything): unknown counts as "ask for every command",
    so a harmless command in the sandbox still shows its card (#398 review, F4)."""
    from server.orchestrator import tool_loop
    from server.services import command_sandbox, terminal_exec

    async def unreadable(_session):
        raise OSError("database is locked")
    monkeypatch.setattr(settings_service, "shell_confirm_policy", unreadable)
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    assert await tool_loop._asks_for_everything() is True
    asked, ran = [], []

    async def card(command, argv, **kw):
        asked.append(command)
        return False

    async def run(command, **kw):
        ran.append(command)
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}
    monkeypatch.setattr(terminal_exec, "run", run)

    async def resolve():
        return [{"key": "run_command", "description": "run"}]
    await tool_loop._dispatch_tool("run_command", {"command": "ls"}, "{}", resolve_tools=resolve,
                                   emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
                                   confirm_command=card, conversation_id="c-unreadable")
    assert asked == ["ls"] and ran == []


async def test_the_bench_instance_asks_as_the_run_said(client, monkeypatch):
    """The driver's settings, through the settings API the bench writes them with: the instance's policy is the
    run's (ask_risky unless BENCH_SHELL_POLICY says ask_all), whatever the app's own default."""
    from server.db import session as db_session
    from scripts.kernel_bench.arslan_driver import settings_body
    monkeypatch.delenv("BENCH_ARSLAN_SETTINGS", raising=False)
    for asked in (None, "ask_all", "ask_risky"):
        if asked is None:
            monkeypatch.delenv("BENCH_SHELL_POLICY", raising=False)
        else:
            monkeypatch.setenv("BENCH_SHELL_POLICY", asked)
        body = {k: v for k, v in settings_body("/run").items() if k != "workspace_dir"}
        assert (await client.put("/api/v1/settings", json=body)).status_code == 200
        async with db_session.AsyncSessionLocal() as session:
            assert await settings_service.shell_confirm_policy(session) == (asked or "ask_risky")
