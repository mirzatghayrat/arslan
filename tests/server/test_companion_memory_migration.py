import json

import pytest
from sqlalchemy import create_engine, event, insert, select, text
from sqlalchemy.exc import IntegrityError

from server.db.models import (
    Base, Learning, MemoryEntry, MemoryLegacyMap, MemoryMigrationReport,
    MemoryRevision, MemorySource, MemoryStoreState, Spawn, UserFact,
)
from server.services.memory_migration import migrate_legacy_sync


@pytest.fixture
def store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'memory.db'}")
    @event.listens_for(engine, "connect")
    def pragmas(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
    with engine.begin() as db:
        Base.metadata.create_all(db)
    yield engine
    engine.dispose()


def rows(db, model):
    return list(db.execute(select(model.__table__)).mappings())


def seed(db):
    db.execute(insert(Spawn), [
        {"id": 1, "name": "A", "domain_category": "test", "system_prompt": "test",
         "memory_facts": ["same preference"]},
        {"id": 2, "name": "B", "domain_category": "test", "system_prompt": "test",
         "memory_facts": ["same preference"]},
    ])
    db.execute(insert(UserFact), [
        {"id": 1, "content": "Known manual", "source": "manual", "sensitive": False,
         "provenance": {"source_kind": "manual", "via": "api"}},
        {"id": 2, "content": "Unknown source", "source": "auto", "sensitive": None, "provenance": None},
        {"id": 3, "content": "Inferred", "source": "auto", "sensitive": False,
         "provenance": {"source_kind": "router"}},
    ])
    db.execute(insert(Learning), [
        {"id": 1, "content": "same lesson", "source_kind": "agentic", "source_ref": {"spawn_id": 1}, "spawn_id": 1},
        {"id": 2, "content": "same lesson", "source_kind": "agentic", "source_ref": {"spawn_id": 2}, "spawn_id": 2},
    ])


def test_empty_and_repeated_migration_are_idempotent(store):
    with store.begin() as db:
        assert migrate_legacy_sync(db)["new_entries"] == 0
    with store.begin() as db:
        assert migrate_legacy_sync(db)["new_entries"] == 0
        assert len(rows(db, MemoryStoreState)) == len(rows(db, MemoryMigrationReport)) == 1


def test_legacy_contents_scopes_and_unknown_confirmation_are_preserved(store):
    with store.begin() as db:
        seed(db)
        before = rows(db, UserFact)
        summary = migrate_legacy_sync(db)
        assert summary["new_entries"] == 7 and summary["legacy_rows_modified"] == 0
        assert rows(db, UserFact) == before
        entries = {row["id"]: row for row in rows(db, MemoryEntry)}
        mapping = {(r["source_table"], r["source_key"]): entries[r["entry_id"]] for r in rows(db, MemoryLegacyMap)}
        assert mapping["user_facts", "1"]["status"] == "active"
        assert mapping["user_facts", "2"]["status"] == "quarantined"
        assert mapping["user_facts", "3"]["status"] == "proposed"
        assert all(r["use_policy"] == "local_only" for r in entries.values())
        for table, keys in (("learnings", ["1", "2"]), ("spawns", ["1:0", "2:0"])):
            assert mapping[table, keys[0]]["id"] != mapping[table, keys[1]]["id"]
            assert mapping[table, keys[0]]["scope_id"] == "1"
            assert mapping[table, keys[1]]["scope_id"] == "2"
        assert len(rows(db, MemoryRevision)) == len(rows(db, MemorySource)) == 7
    with store.begin() as db:
        assert migrate_legacy_sync(db)["new_entries"] == 0


def test_crash_rolls_back_and_retry_has_no_partial_rows(store):
    with store.begin() as db:
        seed(db)
    with pytest.raises(RuntimeError, match="synthetic"):
        with store.begin() as db:
            migrate_legacy_sync(db, fault_after=2)
    with store.begin() as db:
        assert rows(db, MemoryEntry) == []
        assert migrate_legacy_sync(db)["new_entries"] == 7


def test_changed_legacy_source_does_not_silently_overwrite_snapshot(store):
    with store.begin() as db:
        seed(db)
        migrate_legacy_sync(db)
    with store.begin() as db:
        db.execute(text("UPDATE user_facts SET content='changed' WHERE id=1"))
    with pytest.raises(ValueError, match="changed after snapshot"):
        with store.begin() as db:
            migrate_legacy_sync(db)


def test_secret_value_not_copied_into_new_content_or_source(store):
    secret = "sk-proj-" + "A" * 30
    with store.begin() as db:
        db.execute(insert(UserFact).values(id=1, content=secret, source="manual",
                   sensitive=False, provenance={"source_kind": "manual", "body": secret}))
        migrate_legacy_sync(db)
        assert rows(db, MemoryEntry)[0]["use_policy"] == "never"
        assert rows(db, MemoryRevision)[0]["content"] is None
        assert secret not in json.dumps(rows(db, MemorySource)[0]["source_ref"])
        assert rows(db, UserFact)[0]["content"] == secret  # Existing recovery input is preserved.


def test_dangling_and_cyclic_supersession_are_quarantined(store):
    with store.begin() as db:
        seed(db)
        db.execute(text("UPDATE user_facts SET superseded_by=2 WHERE id=1"))
        db.execute(text("UPDATE user_facts SET superseded_by=1 WHERE id=2"))
        db.execute(text("UPDATE user_facts SET superseded_by=999 WHERE id=3"))
        summary = migrate_legacy_sync(db)
        assert summary["notes"]["cyclic_supersession_entries"] == 2
        assert summary["notes"]["dangling_or_cross_scope_supersession"] == 1
        mapped = [r for r in rows(db, MemoryEntry) if r["scope_kind"] == "global"]
        assert all(r["status"] == "quarantined" for r in mapped)


def test_dangling_source_is_not_claimed_as_confirmed_context(store):
    with store.begin() as db:
        db.execute(insert(UserFact).values(id=1, content="unknown provenance", source="auto",
                   provenance={"source_kind": "router", "conversation_id": "missing"}))
        assert migrate_legacy_sync(db)["notes"]["dangling_source"] == 1
        assert rows(db, MemoryEntry)[0]["status"] == "quarantined"


def test_revision_cannot_point_to_another_entry(store):
    with store.begin() as db:
        seed(db)
        migrate_legacy_sync(db)
        first, second = rows(db, MemoryEntry)[:2]
    with pytest.raises(IntegrityError):
        with store.begin() as db:
            db.execute(text("UPDATE memory_entries SET current_revision_id=:r WHERE id=:e"),
                       {"r": second["current_revision_id"], "e": first["id"]})
