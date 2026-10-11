"""0.1.61 §A5/§A8: the permission store — rules, grants, the ledger, and the legacy
"don't ask again" list now living in it."""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa

from server.db import session as db_session
from server.services import permission_store, terminal_policy


@pytest.fixture(autouse=True)
def _fresh(execution_db):
    permission_store._reset_for_tests()
    yield


async def test_a_rule_is_found_by_kind_and_target_and_added_once():
    async with db_session.AsyncSessionLocal() as db:
        a = await permission_store.add_rule(db, "app", "com.tencent.xinWeChat", label="WeChat",
                                            created_from="c1")
        b = await permission_store.add_rule(db, "app", "com.tencent.xinWeChat", label="WeChat")
        await db.commit()
        assert a.id == b.id
        assert (await permission_store.find_rule(db, "app", "com.tencent.xinWeChat")).label == "WeChat"
        assert await permission_store.find_rule(db, "app", "com.apple.Notes") is None
        assert await permission_store.find_rule(db, "shortcut", "com.tencent.xinWeChat") is None


async def test_a_conversation_grant_covers_every_task_and_a_task_grant_only_its_task():
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_grant(db, "conv-1", "", "schedule", "*")
        await permission_store.add_grant(db, "conv-1", "turn-a", "app", "com.apple.Notes")
        await db.commit()
        assert await permission_store.find_grant(db, "conv-1", "turn-z", "schedule", "*")
        assert await permission_store.find_grant(db, "conv-1", "turn-a", "app", "com.apple.Notes")
        assert await permission_store.find_grant(db, "conv-1", "turn-b", "app", "com.apple.Notes") is None
        assert await permission_store.find_grant(db, "conv-2", "turn-a", "app", "com.apple.Notes") is None
        assert await permission_store.find_grant(db, None, "turn-a", "app", "com.apple.Notes") is None


async def test_the_ledger_keeps_90_days_and_lists_policy_refusals():
    async with db_session.AsyncSessionLocal() as db:
        old = await permission_store.record(db, kind="app", target="x", mode="standard",
                                            decided_by="user", decision="allow")
        old.created_at = datetime.utcnow() - timedelta(days=91)
        await permission_store.record(db, kind="schedule", target="*", mode="standard",
                                      decided_by="policy", decision="deny", conversation_id="c")
        await db.commit()
        permission_store._reset_for_tests()          # let the next write prune
        await permission_store.record(db, kind="app", target="y", mode="standard",
                                      decided_by="rule", decision="allow")
        await db.commit()
        targets = [e.target for e in await permission_store.recent(db)]
        assert "x" not in targets and {"y", "*"} <= set(targets)
        refused = await permission_store.refused_since(db, datetime.utcnow() - timedelta(hours=24))
        assert [(e.kind, e.decided_by) for e in refused] == [("schedule", "policy")]


async def test_legacy_dont_ask_again_rules_live_in_the_store():
    async with db_session.AsyncSessionLocal() as db:
        await terminal_policy.allow_always(db, "delete")
        await terminal_policy.allow_always(db, "hermes:recursive delete")
        await terminal_policy.allow_always(db, "sudo")           # forbidden: never stored
        assert await terminal_policy.always_allowed(db) == {"delete", "hermes:recursive delete"}
        rows = await permission_store.list_rules(db, "legacy_rule")
        assert {r.target for r in rows} == {"delete", "hermes:recursive delete"}
        await terminal_policy.forget(db, "delete")
        assert await terminal_policy.always_allowed(db) == {"hermes:recursive delete"}


def test_migration_0067_copies_the_old_list_once(tmp_path):
    from server.db.migrations.versions import _0067_permissions as m
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE settings (key VARCHAR(100) PRIMARY KEY, value TEXT NOT NULL)")
        conn.exec_driver_sql("INSERT INTO settings VALUES ('terminal_always_allow', "
                             "'[\"hermes:script execution via heredoc\", \"delete\"]')")
        m.upgrade_sync(conn)
        m.upgrade_sync(conn)                                     # idempotent
        rows = conn.exec_driver_sql(
            "SELECT kind, target, created_from FROM permission_rules ORDER BY target").fetchall()
    assert rows == [("legacy_rule", "delete", "migration"),
                    ("legacy_rule", "hermes:script execution via heredoc", "migration")]


# ── What the callers (permissions.decide, the approvals API) rely on beyond the cases above ──


async def test_a_remembered_command_rule_keeps_the_words_the_card_used():
    async with db_session.AsyncSessionLocal() as db:
        await terminal_policy.allow_always(db, "git-push")
        await terminal_policy.allow_always(db, "hermes:recursive delete")
        rows = await permission_store.list_rules(db, "legacy_rule")
    assert {r.target: (r.label, r.created_from) for r in rows} == {
        "git-push": ("publishes to a remote repository", "card"),
        "hermes:recursive delete": ("recursive delete", "card")}


async def test_a_rule_keeps_its_use_count_and_is_deleted_by_id_or_by_target():
    async with db_session.AsyncSessionLocal() as db:
        notes = await permission_store.add_rule(db, "app", "com.apple.Notes")
        push = await permission_store.add_rule(db, "legacy_rule", "git-push")
        await permission_store.touch_rule(db, notes)
        await permission_store.touch_rule(db, notes)
        await db.commit()
        notes_id = notes.id
    async with db_session.AsyncSessionLocal() as db:        # a new session: what was committed
        notes = await permission_store.find_rule(db, "app", "com.apple.Notes")
        push = await permission_store.find_rule(db, "legacy_rule", "git-push")
        assert (notes.use_count, notes.last_used_at is not None) == (2, True)
        assert (push.use_count, push.last_used_at) == (0, None)
        # newest first; a kind narrows the list
        everything = await permission_store.list_rules(db)
        assert [r.target for r in everything] == ["git-push", "com.apple.Notes"]
        apps = await permission_store.list_rules(db, "app")
        assert [r.target for r in apps] == ["com.apple.Notes"]
        assert await permission_store.delete_rule(db, notes_id) is True
        assert await permission_store.delete_rule_by(db, "legacy_rule", "git-push") is True
        await db.commit()
        assert await permission_store.delete_rule(db, notes_id) is False       # already gone
        assert await permission_store.delete_rule_by(db, "legacy_rule", "git-push") is False
        assert await permission_store.list_rules(db) == []


async def test_a_grant_is_added_once_per_conversation_task_kind_and_target():
    async with db_session.AsyncSessionLocal() as db:
        a = await permission_store.add_grant(db, "conv-1", "turn-a", "app", "com.apple.Notes",
                                             call_id="c1")
        b = await permission_store.add_grant(db, "conv-1", "turn-a", "app", "com.apple.Notes",
                                             call_id="c2")
        other_task = await permission_store.add_grant(db, "conv-1", "turn-b", "app",
                                                      "com.apple.Notes")
        await db.commit()
        assert a.id == b.id and a.id != other_task.id
        assert a.call_id == "c1"                       # the first answer stays the record of it


async def test_a_stale_task_grant_is_pruned_but_a_conversation_grant_never_is():
    async with db_session.AsyncSessionLocal() as db:
        task = await permission_store.add_grant(db, "conv-1", "turn-a", "app", "com.apple.Notes")
        chat = await permission_store.add_grant(db, "conv-1", "", "schedule", "*")
        task.created_at = chat.created_at = datetime.utcnow() - timedelta(days=7)
        await db.commit()
        permission_store._reset_for_tests()          # let the next write prune
        await permission_store.add_grant(db, "conv-1", "turn-b", "app", "com.apple.Mail")
        await db.commit()
        notes = await permission_store.find_grant(db, "conv-1", "turn-a", "app", "com.apple.Notes")
        assert notes is None
        assert await permission_store.find_grant(db, "conv-1", "turn-z", "schedule", "*")
        assert await permission_store.find_grant(db, "conv-1", "turn-b", "app", "com.apple.Mail")


async def test_the_ledger_lists_newest_first_and_honours_the_limit():
    async with db_session.AsyncSessionLocal() as db:
        for n in range(5):
            await permission_store.record(db, kind="app", target=f"t{n}", mode="standard",
                                          decided_by="user", decision="allow")
        await db.commit()
        newest_first = await permission_store.recent(db)
        assert [e.target for e in newest_first] == ["t4", "t3", "t2", "t1", "t0"]
        assert [e.target for e in await permission_store.recent(db, limit=2)] == ["t4", "t3"]


async def test_only_policy_refusals_inside_the_window_are_listed_as_refused():
    async with db_session.AsyncSessionLocal() as db:
        stale = await permission_store.record(db, kind="schedule", target="old", mode="standard",
                                              decided_by="policy", decision="deny")
        stale.created_at = datetime.utcnow() - timedelta(days=2)
        for decided_by, decision, target in (("policy", "deny", "refused"), ("user", "deny", "no"),
                                             ("policy", "allow", "fine"),
                                             ("reviewer", "deny", "risky")):
            await permission_store.record(db, kind="app", target=target, mode="standard",
                                          decided_by=decided_by, decision=decision)
        await db.commit()
        day = await permission_store.refused_since(db, datetime.utcnow() - timedelta(hours=24))
        assert [e.target for e in day] == ["refused"]
        week = await permission_store.refused_since(db, datetime.utcnow() - timedelta(days=7))
        assert [e.target for e in week] == ["refused", "old"]


async def test_a_deleted_rules_id_is_never_given_to_a_new_rule():
    """The ledger keeps `rule_id` as a plain number, so an id must not come back."""
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_rule(db, "app", "com.apple.Notes")
        newest = await permission_store.add_rule(db, "app", "com.apple.Mail")
        gone = newest.id
        await db.commit()
        assert await permission_store.delete_rule(db, gone) is True
        await db.commit()
        later = await permission_store.add_rule(db, "app", "com.apple.Reminders")
        await db.commit()
        assert later.id > gone


async def _add_row(db, table: str, n: int):
    if table == "grant":
        return await permission_store.add_grant(db, "conv-1", "", "app", f"t{n}")
    return await permission_store.record(db, kind="app", target=f"t{n}", mode="standard",
                                         decided_by="user", decision="allow")


@pytest.mark.parametrize("table", ["grant", "ledger"])
async def test_a_deleted_rows_id_is_never_given_to_a_new_row(table):
    """Same for a grant (the ledger's `grant_id`) and for the ledger's own rows."""
    async with db_session.AsyncSessionLocal() as db:
        await _add_row(db, table, 1)
        newest = await _add_row(db, table, 2)
        gone = newest.id
        await db.delete(newest)
        await db.commit()
        later = await _add_row(db, table, 3)
        await db.commit()
        assert later.id > gone


@contextlib.asynccontextmanager
async def _overlapping_sessions(count: int):
    """`count` sessions that each already hold their own connection, so that the work the test
    then starts on all of them really overlaps (opening a connection takes longer than an add)."""
    async with contextlib.AsyncExitStack() as stack:
        sessions = [await stack.enter_async_context(db_session.AsyncSessionLocal())
                    for _ in range(count)]
        for db in sessions:
            await db.connection()
        yield sessions


async def test_sessions_adding_the_same_rule_at_once_all_get_the_one_row():
    async def add(n, db):
        rule = await permission_store.add_rule(db, "app", "com.apple.Notes", label=f"label-{n}")
        await db.commit()
        return rule.id

    async with _overlapping_sessions(4) as sessions:
        ids = await asyncio.gather(*(add(n, db) for n, db in enumerate(sessions)))
    assert len(set(ids)) == 1
    async with db_session.AsyncSessionLocal() as db:
        [row] = await permission_store.list_rules(db)
        assert row.id == ids[0] and row.label in {f"label-{n}" for n in range(4)}


async def test_sessions_adding_the_same_grant_at_once_all_get_the_one_row():
    async def add(n, db):
        grant = await permission_store.add_grant(db, "conv-1", "turn-a", "app", "com.apple.Notes",
                                                 call_id=f"c{n}")
        await db.commit()
        return grant.id

    async with _overlapping_sessions(4) as sessions:
        ids = await asyncio.gather(*(add(n, db) for n, db in enumerate(sessions)))
    assert len(set(ids)) == 1
    async with db_session.AsyncSessionLocal() as db:
        found = await permission_store.find_grant(db, "conv-1", "turn-a", "app", "com.apple.Notes")
        assert found.id == ids[0] and found.call_id in {f"c{n}" for n in range(4)}


@pytest.mark.parametrize("old_value", ["not json", "5", "null"])
def test_migration_0067_copies_nothing_from_a_list_it_cannot_read(tmp_path, old_value):
    """A standing permission is never inferred from an error (terminal_policy's rule)."""
    from server.db.migrations.versions import _0067_permissions as m
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE settings (key VARCHAR(100) PRIMARY KEY, value TEXT NOT NULL)")
        conn.exec_driver_sql(
            "INSERT INTO settings VALUES ('terminal_always_allow', ?)", (old_value,))
        m.upgrade_sync(conn)
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM permission_rules").scalar() == 0


def test_migration_0067_runs_on_a_database_with_no_settings_table(tmp_path):
    from server.db.migrations.versions import _0067_permissions as m
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        m.upgrade_sync(conn)
        tables = {r[0] for r in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"permission_rules", "permission_grants", "approval_events"} <= tables


def _index_names(conn) -> dict[str, list[str]]:
    inspector = sa.inspect(conn)
    return {t: sorted(i["name"] for i in inspector.get_indexes(t))
            for t in ("permission_rules", "permission_grants", "approval_events")}


def test_migration_0067_and_create_all_build_the_same_indexes(tmp_path):
    """Boot runs create_all and then the migration. Its IF NOT EXISTS has to find what
    create_all built, by name, or every install carries a second index on the same column."""
    from server.db.migrations.versions import _0067_permissions as m
    from server.db.models import Base
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'created.db'}")
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        built = _index_names(conn)
        m.upgrade_sync(conn)
        assert _index_names(conn) == built                      # the migration adds none
    bare = sa.create_engine(f"sqlite:///{tmp_path / 'bare.db'}")
    with bare.begin() as conn:
        m.upgrade_sync(conn)
        assert _index_names(conn) == built                      # and alone it builds the same


async def test_an_old_dont_ask_again_list_is_honoured_after_the_migration():
    """The upgrade, end to end: a list 0.1.60 saved in settings, the migration, then the
    reader every caller uses. Before the migration the old row alone grants nothing."""
    from server.db.migrations.versions import _0067_permissions as m
    from server.services import settings_service
    async with db_session.AsyncSessionLocal() as db:
        await settings_service._set_raw(db, "terminal_always_allow",
                                        '["install", "hermes:recursive delete"]')
        await db.commit()
        assert await terminal_policy.always_allowed(db) == set()
        await (await db.connection()).run_sync(m.upgrade_sync)
        await db.commit()
        assert await terminal_policy.always_allowed(db) == {"install", "hermes:recursive delete"}
