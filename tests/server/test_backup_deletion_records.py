import copy
import json
import sqlite3

import pytest

from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
from server.services import backup, memory_deletion_ledger as ledger
from server.services.memory_deletion_manifest import decode, export_sync
from server.services.memory_repository import repository


@pytest.fixture
async def recovery(execution_db, tmp_path):
    entries = []
    async with repository() as repo:
        for text in ("Synthetic first deletion", "Synthetic second deletion"):
            entries.append(await repo.create(MemoryWrite(content=text, scope=MemoryScope(kind="global")), MemoryActor(origin="user")))
    archive = tmp_path / "old.zip"
    backup.create(tmp_path, archive, db_path=tmp_path / "execution.db")
    snapshots = []
    for entry in entries:
        async with repository() as repo:
            await repo.delete_entry(entry["id"], entry["version"], MemoryActor(origin="user"))
        async with execution_db() as db:
            snapshots.append(await db.run_sync(lambda session: export_sync(session.connection())))
    return {"archive": archive, "database": tmp_path / "execution.db", "entries": entries,
            "snapshots": snapshots, "instance": decode(snapshots[-1])["instance_id"]}


@pytest.mark.parametrize("mode", ["current", "lagging", "missing", "ledger_ahead", "import_newest", "older_import"])
async def test_restore_selects_latest_consistent_records_and_never_modifies_inputs(recovery, tmp_path, mode):
    data = recovery
    current = data["database"]
    root = current.parent / ledger.DIRECTORY
    record = root / (data["instance"] + ".json")
    imported = None
    expected_source = "current_database"
    if mode == "lagging":
        record.write_bytes(data["snapshots"][0])
    elif mode == "missing":
        record.unlink()
    elif mode in {"ledger_ahead", "import_newest"}:
        # A stopped older DB plus an independently newer ledger must never
        # downgrade that ledger just because the DB snapshot is older.
        older = tmp_path / "older-installation"
        backup.restore(data["archive"], older)
        current = older / "arslan.db"
        root = older / ledger.DIRECTORY
        record = root / (data["instance"] + ".json")
        ledger.persist(root, data["snapshots"][-1 if mode == "ledger_ahead" else 0])
        expected_source = "local_ledger" if mode == "ledger_ahead" else "imported_manifest"
        if mode == "import_newest":
            imported = data["snapshots"][-1]
    elif mode == "older_import":
        imported = data["snapshots"][0]

    archive_before = data["archive"].read_bytes()
    database_before = current.read_bytes()
    record_before = record.read_bytes() if record.exists() else None
    target = tmp_path / "restored"
    result = backup.restore(data["archive"], target, current_db_path=current, deletion_manifest=imported)
    assert result["deletion_reconciliation"] == {"applied": True, "deleted_entries": 2, "deletion_epoch": 2}
    selection = result["deletion_record_selection"]
    assert selection["selected_source"] == expected_source
    assert selection["local_ledger_present"] == (mode != "missing")
    assert selection["deletion_epoch"] == 2
    with sqlite3.connect(target / "arslan.db") as db:
        assert db.execute("SELECT status FROM memory_entries ORDER BY id").fetchall() == [("deleted",), ("deleted",)]
        assert db.execute("SELECT content FROM memory_revisions").fetchall() == [(None,), (None,)]
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert data["archive"].read_bytes() == archive_before
    assert current.read_bytes() == database_before
    assert (record.read_bytes() if record.exists() else None) == record_before
    assert not list(tmp_path.glob(".arslan-restore-*"))


@pytest.mark.parametrize("mode", ["corrupt_ledger", "foreign_ledger", "unsafe_permissions", "foreign_import",
                                 "same_epoch_conflict", "older_history_conflict", "missing_current"])
async def test_ambiguous_or_unreadable_current_records_refuse_install(recovery, tmp_path, mode):
    data = recovery
    current = data["database"]
    record = current.parent / ledger.DIRECTORY / (data["instance"] + ".json")
    imported = None
    if mode == "corrupt_ledger":
        record.write_bytes(b"corrupt synthetic record")
        imported = data["snapshots"][-1]  # A valid import must not hide corrupt local evidence.
    elif mode == "foreign_ledger":
        value = decode(data["snapshots"][-1])
        value["instance_id"] = "00000000-0000-4000-8000-000000000999"
        record.write_bytes(json.dumps(value).encode())
    elif mode == "unsafe_permissions":
        record.chmod(0o644)
    elif mode == "missing_current":
        current = tmp_path / "missing.db"
    else:
        value = copy.deepcopy(decode(data["snapshots"][0 if mode == "older_history_conflict" else -1]))
        if mode == "foreign_import":
            value["instance_id"] = "00000000-0000-4000-8000-000000000999"
        else:
            value["deletions"][0]["entry_id"] = "00000000-0000-4000-8000-000000000999"
        imported = json.dumps(value).encode()
    original = data["archive"].read_bytes()
    record_before = record.read_bytes()
    target = tmp_path / "refused"
    error = {
        "corrupt_ledger": "invalid_deletion_manifest",
        "foreign_ledger": "deletion_ledger_store_mismatch",
        "unsafe_permissions": "unsafe_deletion_ledger_storage",
        "foreign_import": "deletion_manifest_store_mismatch",
        "same_epoch_conflict": "deletion_ledger_history_conflict",
        "older_history_conflict": "deletion_ledger_history_conflict",
        "missing_current": "deletion_current_database_unavailable",
    }[mode]
    with pytest.raises(ValueError, match=f"^{error}$"):
        backup.restore(data["archive"], target, current_db_path=current, deletion_manifest=imported)
    assert not target.exists() and not list(tmp_path.glob(".arslan-restore-*"))
    assert data["archive"].read_bytes() == original
    assert record.read_bytes() == record_before


async def test_offline_cli_wires_current_installation_and_import(recovery, tmp_path, monkeypatch, capsys):
    from scripts import backup_data

    imported = tmp_path / "export.json"
    imported.write_bytes(recovery["snapshots"][0])
    target = tmp_path / "cli-restored"
    monkeypatch.setattr("sys.argv", ["backup_data", "restore", "--archive", str(recovery["archive"]),
                                    "--new-data-dir", str(target), "--current-db-path", str(recovery["database"]),
                                    "--deletion-manifest", str(imported)])
    backup_data.main()
    result = json.loads(capsys.readouterr().out)
    assert result["deletion_reconciliation"]["deleted_entries"] == 2
    assert result["deletion_record_selection"]["sources_checked"] == ["current_database", "local_ledger", "imported_manifest"]


async def test_new_machine_without_later_records_still_quarantines(recovery, tmp_path):
    target = tmp_path / "new-machine"
    result = backup.restore(recovery["archive"], target)
    assert result["deletion_reconciliation"] == {"applied": False, "reason": "no_deletion_manifest"}
    assert result["deletion_record_selection"] == {"selected_source": "none"}
    with sqlite3.connect(target / "arslan.db") as db:
        assert db.execute("SELECT status FROM memory_entries").fetchall() == [("quarantined",), ("quarantined",)]


async def test_running_profile_refuses_restore_before_staging_and_releases_afterward(recovery, tmp_path):
    from server.services.data_profile_lock import hold

    target = tmp_path / "must-stay-absent"
    with hold(recovery["database"]):
        with pytest.raises(ValueError, match="^data_profile_in_use$"):
            backup.restore(recovery["archive"], target, current_db_path=recovery["database"])
        assert not target.exists() and not list(tmp_path.glob(".arslan-restore-*"))
    result = backup.restore(recovery["archive"], target, current_db_path=recovery["database"])
    assert result["deletion_reconciliation"]["deleted_entries"] == 2
    with hold(recovery["database"]):
        pass


async def test_new_machine_cli_can_import_later_record_without_current_database(recovery, tmp_path, monkeypatch, capsys):
    from scripts import backup_data

    imported = tmp_path / "latest-export.json"
    imported.write_bytes(recovery["snapshots"][-1])
    target = tmp_path / "new-machine-imported"
    monkeypatch.setattr("sys.argv", ["backup_data", "restore", "--archive", str(recovery["archive"]),
                                    "--new-data-dir", str(target), "--deletion-manifest", str(imported)])
    backup_data.main()
    result = json.loads(capsys.readouterr().out)
    assert result["deletion_reconciliation"]["deleted_entries"] == 2
    assert result["deletion_record_selection"] == {"selected_source": "imported_manifest"}


@pytest.mark.parametrize("mode", ["malformed", "symlink", "oversized"])
async def test_offline_cli_rejects_unsafe_import_before_creating_restore(recovery, tmp_path, monkeypatch, mode):
    from scripts import backup_data
    from server.services import memory_deletion_manifest

    imported = tmp_path / "unsafe-import.json"
    if mode == "symlink":
        source = tmp_path / "source-export.json"
        source.write_bytes(recovery["snapshots"][-1])
        imported.symlink_to(source)
    elif mode == "oversized":
        monkeypatch.setattr(memory_deletion_manifest, "MAX_BYTES", 8)
        imported.write_bytes(b"x" * 9)
    else:
        imported.write_bytes(b'{"format":1,"format":1}')
    target = tmp_path / "never-created"
    monkeypatch.setattr("sys.argv", ["backup_data", "restore", "--archive", str(recovery["archive"]),
                                    "--new-data-dir", str(target), "--deletion-manifest", str(imported)])
    with pytest.raises((ValueError, OSError)):
        backup_data.main()
    assert not target.exists() and not list(tmp_path.glob(".arslan-restore-*"))
