"""C7c-5b (v0.1.64): the expert-era models are gone; a new install builds no expert table, an upgraded one still
boots and writes.

Booted the way the app boots (storage_boot.initialize on build_engine, foreign keys on). The upgraded shape
comes from the frozen pre-C7c-5b CREATE text (tests/server/pre_0103.py), since the models cannot make it any
more. Since C7c-5c the same boot runs 0103, which drops those tables (tests/server/test_migration_0103.py).
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.db import models
from server.db.migrations import runner
from server.db.session import build_engine
from server.services import storage_boot
from tests.server import pre_0103

REMOVED_MODELS = ("Spawn", "ChatMessage", "Feedback", "SpawnCapability", "SpawnPhase", "ConversationSpawn",
                  "EvolutionProposal", "SyntheticTask", "EvolutionAttempt", "SpawnCollection", "PersonaSeed",
                  "RecipeVersion", "RecipeExecution")
EXPERT_TABLES = {"spawns", "chat_messages", "feedback", "spawn_capabilities", "spawn_phases",
                 "conversation_spawns", "spawn_collections", "evolution_proposals", "synthetic_tasks",
                 "evolution_attempts", "persona_seeds"}
# Made by old migrations on every install (0015, 0046) and naming no expert table; 0103 drops them (C7c-5c).
LEFT_FOR_0103 = {"persona_seeds_fts", "recipe_versions", "recipe_executions"}


# 0046 since C7c-5b: the CREATE text create_all made at C7c-4, copied from sqlite_master after a fresh boot.
RECIPE_SQL = {
    'ix_recipe_versions_key': 'CREATE INDEX ix_recipe_versions_key ON recipe_versions ("key")',
    'recipe_executions': 'CREATE TABLE recipe_executions (\n\tid INTEGER NOT NULL, \n\trequest_key VARCHAR(80) NOT NULL, \n\trecipe_id INTEGER NOT NULL, \n\tinput TEXT NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tcheckpoint JSON NOT NULL, \n\trun_id INTEGER, \n\terror TEXT, \n\tcreated_at DATETIME, \n\tupdated_at DATETIME, \n\tPRIMARY KEY (id), \n\tUNIQUE (request_key), \n\tFOREIGN KEY(recipe_id) REFERENCES recipe_versions (id)\n)',
    'recipe_versions': 'CREATE TABLE recipe_versions (\n\tid INTEGER NOT NULL, \n\t"key" VARCHAR(60) NOT NULL, \n\tversion INTEGER NOT NULL, \n\tname VARCHAR(100) NOT NULL, \n\tspec JSON NOT NULL, \n\tcreated_at DATETIME, \n\tPRIMARY KEY (id), \n\tUNIQUE ("key", version)\n)',
}


async def _boot(db_path) -> None:
    engine = build_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await storage_boot.initialize(engine)
    finally:
        await engine.dispose()


def _rows(db_path, query, params=()) -> list[tuple]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return [tuple(row) for row in conn.exec_driver_sql(query, params)]
    finally:
        engine.dispose()


def _tables(db_path) -> set[str]:
    return {name for (name,) in _rows(db_path, "SELECT name FROM sqlite_master WHERE type='table'")}


async def _write_one_of_each(db_path) -> dict[str, int]:
    """A run, a scheduled task and a message with spawn_id NULL, and a collection deleted, through the ORM with
    foreign keys on, as the app writes them."""
    engine = build_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as db:
            run = models.Run(conversation_id="c1", user_message="hi", spawn_id=None)
            task = models.ScheduledTask(name="t", prompt="p", spawn_id=None, target="arslan",
                                        schedule_kind="interval", interval_s=3600)
            collection = models.Collection(name="notes")
            db.add_all([run, task, collection])
            await db.flush()
            message = models.ArslanMessage(conversation_id="c1", role="arslan", content="ok", spawn_id=None,
                                           run_id=run.id)
            db.add(message)
            await db.commit()
            await db.delete(collection)          # cascades into spawn_collections where that table exists
            await db.commit()
            return {"run": run.id, "task": task.id, "message": message.id}
    finally:
        await engine.dispose()


def test_the_models_are_gone():
    for name in REMOVED_MODELS:
        assert not hasattr(models, name), name
    assert EXPERT_TABLES.isdisjoint(models.Base.metadata.tables)
    for table in ("runs", "scheduled_tasks", "arslan_messages", "knowledge_chunks"):
        column = models.Base.metadata.tables[table].c.spawn_id
        assert column.nullable and not column.foreign_keys, table


async def test_a_new_install_builds_no_expert_table_and_nothing_names_spawns(tmp_path):
    db = tmp_path / "arslan.db"
    await _boot(db)
    tables = _tables(db)
    assert (EXPERT_TABLES | LEFT_FOR_0103) & tables == set()
    # 0046's inline DDL is what the models made, byte for byte (0103 drops the tables in the same boot).
    from server.db.migrations.versions import _0046_recipes
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            _0046_recipes.upgrade_sync(conn)
            recipe_sql = dict(conn.exec_driver_sql(
                "SELECT name, sql FROM sqlite_master WHERE tbl_name LIKE 'recipe_%' AND sql IS NOT NULL").all())
    finally:
        engine.dispose()
    assert recipe_sql == RECIPE_SQL
    # No table, index or trigger names `spawns`: a foreign key to a missing table refuses every write to its table.
    assert _rows(db, "SELECT type, name FROM sqlite_master WHERE sql LIKE '%spawns%'") == []
    assert {v for (v,) in _rows(db, "SELECT version FROM schema_version")} == {v for v, _ in runner.MIGRATIONS}
    assert _rows(db, "SELECT phase FROM memory_store_state") == [("active",)]
    # 0018 still finds its column on a new install.
    assert "spawn_id" in {row[1] for row in _rows(db, "PRAGMA table_info(knowledge_chunks)")}
    await _write_one_of_each(db)
    assert _rows(db, "PRAGMA foreign_key_check") == []
    await _boot(db)                                   # a second boot changes nothing
    assert _tables(db) == tables


async def _pre_c7c5b_install(db_path, *, activated: bool) -> None:
    """The expert tables an install had before C7c-5b, the four child tables' REFERENCES spawns, an expert
    with one stored preference and one feedback row. Not activated: memory v2 has not run on it yet."""
    if activated:
        await _boot(db_path)
    else:
        engine = sa.create_engine(f"sqlite:///{db_path}")
        try:
            with engine.begin() as conn:
                runner.prepare_upgrade_backup(conn)
                models.Base.metadata.create_all(conn)
                runner.apply_pending(conn)
        finally:
            engine.dispose()
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            pre_0103.load(conn, triggers=activated)
            conn.exec_driver_sql(
                "INSERT INTO spawns (id, name, domain_category, system_prompt, is_default, memory_facts) "
                "VALUES (3, 'Synthetic expert', 'content', 'Synthetic', 0, ?)",
                (json.dumps([] if activated else ["Prefers short answers"]),))
            conn.exec_driver_sql(
                "INSERT INTO feedback (id, spawn_id, session_id, user_action) VALUES (1, 3, 's', 'accept')")
            conn.exec_driver_sql("INSERT INTO collections (id, name) VALUES (7, 'bound to the expert')")
            conn.exec_driver_sql("INSERT INTO spawn_collections (spawn_id, collection_id) VALUES (3, 7)")
    finally:
        engine.dispose()
    pre_0103.restore_child_tables(db_path)


async def test_an_upgraded_install_boots_and_still_writes_with_spawn_id_null(tmp_path):
    db = tmp_path / "arslan.db"
    await _pre_c7c5b_install(db, activated=True)
    assert EXPERT_TABLES <= _tables(db)
    await _boot(db)                                   # 0103 drops them and leaves the empty spawns(id) stub
    assert _tables(db) & EXPERT_TABLES == {"spawns"}
    ids = await _write_one_of_each(db)
    assert _rows(db, "SELECT spawn_id FROM runs WHERE id=?", (ids["run"],)) == [(None,)]
    assert _rows(db, "SELECT spawn_id, target FROM scheduled_tasks WHERE id=?", (ids["task"],)) == [(None, "arslan")]
    assert _rows(db, "SELECT spawn_id FROM arslan_messages WHERE id=?", (ids["message"],)) == [(None,)]
    assert _rows(db, "SELECT count(*) FROM spawns") == [(0,)]
    assert _rows(db, "PRAGMA foreign_key_check") == []


async def test_activating_an_upgraded_install_still_maps_the_expert_preferences(tmp_path):
    """The read guards' other side: where `spawns` and `feedback` exist, the legacy mapping reads them (0103's
    step 0, before it drops them); since C7c-5c the preference lands in global, quarantined. Activation then
    puts no trigger on the stub, which has no memory_facts."""
    db = tmp_path / "arslan.db"
    await _pre_c7c5b_install(db, activated=False)
    await _boot(db)
    assert _rows(db, "SELECT phase FROM memory_store_state") == [("active",)]
    assert _rows(db, "SELECT m.source_table, m.source_key, e.scope_kind, e.status FROM memory_legacy_map m "
                     "JOIN memory_entries e ON e.id = m.entry_id WHERE m.source_table='spawns'") == [
        ("spawns", "3:0", "global", "quarantined")]
    assert _rows(db, "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='spawns'") == []
