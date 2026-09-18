import copy
import json
import sqlite3

import pytest

from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
from server.services import memory_deletion_manifest as manifest
from server.services.memory_repository import repository


def valid():
    return {"format": 1, "instance_id": "00000000-0000-4000-8000-000000000001", "deletion_epoch": 1,
            "deletions": [{"entry_id": "00000000-0000-4000-8000-000000000002", "epoch": 1,
                           "content_digest": "a" * 64, "scope_kind": "global", "scope_key": ""}]}


async def test_export_contains_only_tombstone_metadata_and_roundtrips(execution_db):
    content = "Synthetic deleted report preference"
    async with repository() as repo:
        entry = await repo.create(MemoryWrite(content=content, scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
        await repo.delete_entry(entry["id"], entry["version"], MemoryActor(origin="user"))
    async with execution_db.kw["bind"].begin() as connection:
        payload = await connection.run_sync(manifest.export_sync)
        assert await connection.run_sync(manifest.export_sync) == payload
    result = manifest.decode(payload)
    assert content.encode() not in payload
    assert b"digest_key" not in payload and b"source_ref" not in payload
    assert result["deletion_epoch"] == 1 and len(result["deletions"]) == 1
    assert result["deletions"][0]["entry_id"] == entry["id"]


@pytest.mark.parametrize("mutation", ["extra", "text", "bool_epoch", "future_epoch", "bad_uuid", "bad_digest", "scope", "global_key", "duplicate", "wrong_rows"])
def test_invalid_metadata_fails_closed(mutation):
    value = valid()
    row = value["deletions"][0]
    if mutation == "extra":
        value["digest_key"] = "not allowed"
    elif mutation == "text":
        row["content"] = "not allowed"
    elif mutation == "bool_epoch":
        value["deletion_epoch"] = True
    elif mutation == "future_epoch":
        row["epoch"] = 2
    elif mutation == "bad_uuid":
        row["entry_id"] = "../foreign"
    elif mutation == "bad_digest":
        row["content_digest"] = "plaintext"
    elif mutation == "scope":
        row["scope_kind"] = []
    elif mutation == "global_key":
        row["scope_key"] = "unexpected"
    elif mutation == "duplicate":
        value["deletions"].append(copy.deepcopy(row))
    else:
        value["deletions"] = {}
    with pytest.raises(ValueError, match="^invalid_deletion_manifest$"):
        manifest.decode(json.dumps(value).encode())


@pytest.mark.parametrize("payload", [b'{"format":1,"format":1}', b'\xff', b'[' * 2000])
def test_malformed_json_is_bounded_and_has_no_parser_diagnostics(payload):
    with pytest.raises(ValueError, match="^invalid_deletion_manifest$"):
        manifest.decode(payload)


def test_size_and_entry_limits(monkeypatch):
    payload = json.dumps(valid()).encode()
    monkeypatch.setattr(manifest, "MAX_BYTES", len(payload) - 1)
    with pytest.raises(ValueError, match="invalid_deletion_manifest"):
        manifest.decode(payload)
    monkeypatch.setattr(manifest, "MAX_ENTRIES", 0)
    with pytest.raises(ValueError, match="invalid_deletion_manifest"):
        manifest.validate(valid())


@pytest.mark.parametrize("mode", ["entry_id", "fingerprint", "legacy", "foreign_store", "malformed"])
async def test_old_backup_reconciles_later_deletion_before_install(execution_db, tmp_path, mode):
    from server.services import backup
    from sqlalchemy import create_engine

    content = "Synthetic report preference deleted after backup"
    if mode == "legacy":
        from sqlalchemy import insert
        from server.db.models import UserFact
        from server.services.memory_migration import migrate_legacy_sync
        from server.services.memory_activation import activate_sync
        async with execution_db.kw["bind"].begin() as connection:
            await connection.execute(insert(UserFact).values(id=99, content=content, source="manual",
                                     sensitive=False, provenance={"source_kind": "manual"}))
            await connection.run_sync(migrate_legacy_sync)
            await connection.run_sync(activate_sync)
        async with repository() as repo:
            entry = (await repo.list_entries())[0]
    else:
        async with repository() as repo:
            entry = await repo.create(MemoryWrite(content=content, scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
    archive = tmp_path / "old.zip"
    backup.create(tmp_path, archive, db_path=tmp_path / "execution.db")
    original = archive.read_bytes()
    async with repository() as repo:
        await repo.delete_entry(entry["id"], entry["version"], MemoryActor(origin="user"))
    async with execution_db.kw["bind"].begin() as connection:
        value = manifest.decode(await connection.run_sync(manifest.export_sync))
    if mode == "fingerprint":
        value["deletions"][0]["entry_id"] = "00000000-0000-4000-8000-000000000099"
    elif mode == "foreign_store":
        value["instance_id"] = "00000000-0000-4000-8000-000000000099"
    elif mode == "malformed":
        value["content"] = "must reject"
    payload = json.dumps(value).encode()
    target = tmp_path / "restored"
    if mode in {"foreign_store", "malformed"}:
        with pytest.raises(ValueError, match="deletion_manifest"):
            backup.restore(archive, target, deletion_manifest=payload)
        assert not target.exists()
    else:
        result = backup.restore(archive, target, deletion_manifest=payload)
        assert result["deletion_reconciliation"]["deleted_entries"] == 1
        with sqlite3.connect(target / "arslan.db") as db:
            assert db.execute("SELECT status FROM memory_entries WHERE id=?", (entry["id"],)).fetchone() == ("deleted",)
            assert db.execute("SELECT content FROM memory_revisions WHERE entry_id=?", (entry["id"],)).fetchall() == [(None,)]
            assert db.execute("SELECT count(*) FROM memory_sources WHERE entry_id=?", (entry["id"],)).fetchone() == (0,)
            assert db.execute("SELECT deletion_epoch FROM memory_store_state").fetchone() == (1,)
            assert db.execute("SELECT count(*) FROM memory_deletions").fetchone() == (1,)
            if mode == "legacy":
                assert db.execute("SELECT count(*) FROM legacy_user_facts WHERE id=99").fetchone() == (0,)
                assert db.execute("SELECT count(*) FROM memory_entries_fts").fetchone() == (0,)
        engine = create_engine(f"sqlite:///{target / 'arslan.db'}")
        try:
            with engine.begin() as connection:
                assert manifest.reconcile_staged_sync(connection, payload)["deleted_entries"] == 0
        finally:
            engine.dispose()
    assert archive.read_bytes() == original
