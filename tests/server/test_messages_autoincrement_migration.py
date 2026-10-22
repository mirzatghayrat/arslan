"""0069: a conversation message's id is never handed out again (v0.1.63 S3b, ⓪Plan's Q1).

Undoing a turn deletes the newest messages; without AUTOINCREMENT the next message took a deleted
one's id, which the phone's seenUpTo, the window's resume and a summary's up_to_message_id would
read as already seen. The table is rebuilt with its rows, ids, foreign keys, index and search.
"""
from sqlalchemy.ext.asyncio import create_async_engine

from server.db.migrations.versions._0059_messages_fts import upgrade_sync as fts_0059
from server.db.migrations.versions._0069_message_ids_never_reused import upgrade_sync
from server.db.models import Base
from server.db.session import build_engine

# The pre-0069 shape: arslan_messages as create_all built it, with 0059's search on top.
_PRE_0069 = (
    "CREATE TABLE runs (id INTEGER PRIMARY KEY)",
    "CREATE TABLE spawns (id INTEGER PRIMARY KEY)",
    "CREATE TABLE arslan_summaries (id INTEGER PRIMARY KEY, conversation_id VARCHAR(50) NOT NULL, "
    "summary TEXT NOT NULL, up_to_message_id INTEGER NOT NULL, updated_at DATETIME)",
    "CREATE TABLE arslan_messages (id INTEGER NOT NULL, conversation_id VARCHAR(50) NOT NULL, "
    "role VARCHAR(20) NOT NULL, content TEXT NOT NULL, display_content TEXT, spawn_id INTEGER, "
    "run_id INTEGER, timestamp DATETIME, job_outcome VARCHAR(20), source VARCHAR(20), PRIMARY KEY (id), "
    "FOREIGN KEY(spawn_id) REFERENCES spawns (id), FOREIGN KEY(run_id) REFERENCES runs (id) ON DELETE SET NULL)",
    "CREATE INDEX ix_arslan_messages_conversation_id ON arslan_messages (conversation_id)",
)
_COLUMNS = "id, conversation_id, role, content, display_content, spawn_id, run_id, timestamp, job_outcome, source"
_ROWS = (
    (1, "c1", "user", "plan the garden", None, None, None, "2026-10-01 09:00:00", None, None),
    (2, "c1", "arslan", "tomatoes by the fence", "**tomatoes** by the fence", None, 1, "2026-10-01 09:00:05",
     None, None),
    (3, "c2", "user", "from the phone", None, None, None, "2026-10-01 10:00:00", None, "phone"),
    (4, "c2", "spawn_summary", "helper finished", "full helper output", 1, 2, "2026-10-01 10:00:09", "done",
     None),
    (5, "c1", "user", "and the herbs", None, None, None, "2026-10-01 11:00:00", None, None),
)


async def _legacy_db(path):
    engine = build_engine(f"sqlite+aiosqlite:///{path}")        # foreign_keys=ON, as the app runs it
    async with engine.begin() as conn:
        for ddl in _PRE_0069:
            await conn.exec_driver_sql(ddl)
        await conn.run_sync(fts_0059)
        await conn.exec_driver_sql("INSERT INTO runs (id) VALUES (1), (2)")
        await conn.exec_driver_sql("INSERT INTO spawns (id) VALUES (1)")
        for row in _ROWS:
            await conn.exec_driver_sql(f"INSERT INTO arslan_messages ({_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?)", row)
    return engine


async def _rows(conn):
    return [tuple(r) for r in (await conn.exec_driver_sql(f"SELECT {_COLUMNS} FROM arslan_messages ORDER BY id")).all()]


async def _schema(conn):
    return (await conn.exec_driver_sql(
        "SELECT name, sql FROM sqlite_master WHERE name LIKE 'arslan_messages%' OR name LIKE 'ix_arslan%' "
        "ORDER BY name")).all()


async def _add(conn, content="new") -> int:
    result = await conn.exec_driver_sql(
        "INSERT INTO arslan_messages (conversation_id, role, content) VALUES ('c1', 'user', ?)", (content,))
    return result.lastrowid


async def _found(conn, word) -> list[int]:
    return [r[0] for r in (await conn.exec_driver_sql(
        "SELECT rowid FROM arslan_messages_fts WHERE arslan_messages_fts MATCH ? ORDER BY rowid", (word,))).all()]


async def test_0069_keeps_every_row_and_never_hands_a_deleted_id_out_again(tmp_path):
    engine = await _legacy_db(tmp_path / "m.db")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(upgrade_sync)
        async with engine.begin() as conn:
            assert await _rows(conn) == [tuple(r) for r in _ROWS]
            await conn.exec_driver_sql("DELETE FROM arslan_messages WHERE id = 5")     # an undone turn
            assert await _add(conn) == 6                     # before 0069 it took 5 again
            sql = dict((await _schema(conn)))["arslan_messages"]
            assert "AUTOINCREMENT" in sql.upper()
            assert "ix_arslan_messages_conversation_id" in dict(await _schema(conn))
            keys = {(r[3], r[2], r[6]) for r in (await conn.exec_driver_sql(
                "PRAGMA foreign_key_list(arslan_messages)")).all()}
            assert keys == {("run_id", "runs", "SET NULL"), ("spawn_id", "spawns", "NO ACTION")}
            await conn.exec_driver_sql("DELETE FROM runs WHERE id = 1")
            assert (await conn.exec_driver_sql("SELECT run_id FROM arslan_messages WHERE id = 2")).scalar() is None
    finally:
        await engine.dispose()


async def test_0069_search_finds_old_messages_and_follows_new_ones(tmp_path):
    engine = await _legacy_db(tmp_path / "m.db")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(upgrade_sync)
        async with engine.begin() as conn:
            assert await _found(conn, "tomatoes") == [2]                         # rebuilt from the copy
            new = await _add(conn, "basil on the sill")
            assert await _found(conn, "basil") == [new]                          # the insert trigger
            await conn.exec_driver_sql("UPDATE arslan_messages SET content = 'mint instead' WHERE id = ?", (new,))
            assert await _found(conn, "basil") == [] and await _found(conn, "mint") == [new]
            await conn.exec_driver_sql("DELETE FROM arslan_messages WHERE id = 2")
            assert await _found(conn, "tomatoes") == []                          # the delete trigger
    finally:
        await engine.dispose()


async def test_0069_a_second_run_changes_nothing(tmp_path):
    engine = await _legacy_db(tmp_path / "m.db")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(upgrade_sync)
        async with engine.connect() as conn:
            first = (await _schema(conn), await _rows(conn))
        async with engine.begin() as conn:
            await conn.run_sync(upgrade_sync)
        async with engine.begin() as conn:
            assert (await _schema(conn), await _rows(conn)) == first
            assert await _found(conn, "herbs") == [5]                            # one index row, not two
            assert await _add(conn) == 6
    finally:
        await engine.dispose()


async def test_0069_a_run_or_spawn_that_points_at_nothing_does_not_stop_the_upgrade(tmp_path):
    engine = await _legacy_db(tmp_path / "m.db")
    try:
        plain = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")   # foreign keys off
        async with plain.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO arslan_messages (id, conversation_id, role, content, spawn_id, run_id) "
                "VALUES (6, 'c3', 'arslan', 'orphan', 7, 99)")
        await plain.dispose()
        async with engine.begin() as conn:
            await conn.run_sync(upgrade_sync)
        async with engine.connect() as conn:
            row = (await conn.exec_driver_sql(
                "SELECT conversation_id, content, spawn_id, run_id FROM arslan_messages WHERE id = 6")).one()
            assert tuple(row) == ("c3", "orphan", None, None)
            assert (await _rows(conn))[:5] == [tuple(r) for r in _ROWS]
    finally:
        await engine.dispose()


async def test_0069_starts_past_any_id_a_summary_has_folded_in(tmp_path):
    """A summary that covers ids past the newest message (they were deleted) would hide a new message that
    took one of them from the model's context."""
    engine = await _legacy_db(tmp_path / "m.db")
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO arslan_summaries (conversation_id, summary, up_to_message_id) VALUES ('c1', 's', 8)")
            await conn.run_sync(upgrade_sync)
        async with engine.begin() as conn:
            assert await _add(conn) == 9
    finally:
        await engine.dispose()


async def test_a_fresh_database_never_hands_a_deleted_id_out_again_and_0069_leaves_it(tmp_path):
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'fresh.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(fts_0059)
            first, second = await _add(conn), await _add(conn)
            await conn.exec_driver_sql("DELETE FROM arslan_messages WHERE id = ?", (second,))
            assert await _add(conn) == second + 1 and first == 1
            before = await _schema(conn)
            await conn.run_sync(upgrade_sync)
            assert await _schema(conn) == before
    finally:
        await engine.dispose()
