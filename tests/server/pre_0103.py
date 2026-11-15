"""The expert-era schema from before C7c-5b (v0.1.64), for tests that need an upgraded install's shape.

C7c-5b removed the Spawn model and the other expert-era models, so a test database booted from the models no
longer has their tables. An upgraded install kept them until C7c-5c's migration 0103 dropped them. The CREATE text is frozen in
fixtures/pre_0103_expert_tables.sql (copied from sqlite_master after a fresh boot at C7c-4); load it on a
booted database with foreign keys off, as tests/server/test_migration_0100.py does for 0052's table.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "pre_0103_expert_tables.sql"
CHILD_TABLES = ("arslan_messages", "knowledge_chunks", "runs", "scheduled_tasks")


def statements(section: str) -> list[str]:
    """The statements of one section of the fixture ("tables", "triggers" or "child_tables")."""
    current, chunk, out = None, [], []
    for line in FIXTURE.read_text().splitlines():
        if line.startswith("-- section: "):
            current = line[len("-- section: "):].strip()
            continue
        if current != section or (not chunk and (not line or line.startswith("--"))):
            continue
        if line == ";":
            out.append("\n".join(chunk))
            chunk = []
        else:
            chunk.append(line)
    assert out, f"no section {section!r} in {FIXTURE.name}"
    return out


def load(connection, *, triggers: bool = False) -> None:
    """Create the expert-era tables (and, if asked, activation's two triggers on spawns) through a sync
    SQLAlchemy connection or a sqlite3 connection."""
    run = getattr(connection, "exec_driver_sql", None) or connection.execute
    for statement in statements("tables") + (statements("triggers") if triggers else []):
        run(statement)


def load_sync_session(session) -> None:
    """For `await db.run_sync(pre_0103.load_sync_session)` on an AsyncSession."""
    load(session.connection())


NEW_SCOPE_CHECK = "scope_kind IN ('global','project','domain','task')"
OLD_SCOPE_CHECK = "scope_kind IN ('global','project','domain','expert','task')"
RETIRED_TRIGGERS = ("memory_entries_scope_retired_ins", "memory_entries_scope_retired_upd")


def restore_child_tables(db_path) -> None:
    """Take a booted database back to a pre-0103 install's shape (C7c-5c): 0103 not recorded, its expert-scope
    triggers and `knowledge_chunks.origin_label` gone, `memory_entries` with the CHECK that allowed "expert", and
    the four tables that kept `spawn_id` with their pre-C7c-5b CREATE text (the foreign key to spawns).

    The CREATE text differs only in those clauses, so the stored rows are laid out the same; it is rewritten in
    place. Close every other connection to the file first.
    """
    old = {statement.split()[2]: statement for statement in statements("child_tables")}
    assert set(old) == set(CHILD_TABLES)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("DELETE FROM schema_version WHERE version = '0103'")
        for name in RETIRED_TRIGGERS:
            conn.execute(f"DROP TRIGGER IF EXISTS {name}")
        if "origin_label" in {row[1] for row in conn.execute("PRAGMA table_info(knowledge_chunks)")}:
            conn.execute("ALTER TABLE knowledge_chunks DROP COLUMN origin_label")
        conn.commit()
        memory = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='memory_entries'").fetchone()[0]
        assert NEW_SCOPE_CHECK in memory
        conn.execute("PRAGMA writable_schema=ON")
        for name, sql in {**old, "memory_entries": memory.replace(NEW_SCOPE_CHECK, OLD_SCOPE_CHECK)}.items():
            changed = conn.execute("UPDATE sqlite_master SET sql=? WHERE type='table' AND name=?", (sql, name))
            assert changed.rowcount == 1, name
        conn.commit()
        conn.execute("PRAGMA writable_schema=OFF")
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        for name in CHILD_TABLES:
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]
            assert "REFERENCES spawns" in sql, name


async def add_spawn(db, spawn_id: int, name: str, *, memory_facts: list | None = None,
                    domain_category: str = "d", system_prompt: str = "p") -> None:
    """An upgraded install's expert row, written as text on an AsyncSession (there is no Spawn model since
    C7c-5b). Creates the expert tables first when the database has none."""
    import json

    from sqlalchemy import text
    if (await db.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='spawns'"))).first() is None:
        await db.run_sync(load_sync_session)
    await db.execute(text(
        "INSERT INTO spawns (id, name, domain_category, system_prompt, is_default, memory_facts) "
        "VALUES (:id, :name, :domain_category, :system_prompt, 0, :memory_facts)"),
        {"id": spawn_id, "name": name, "domain_category": domain_category, "system_prompt": system_prompt,
         "memory_facts": json.dumps(memory_facts or [])})
