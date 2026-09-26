import copy
import json
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
from server.services import memory_deletion_ledger as ledger
from server.services.memory_deletion_manifest import decode, export_sync
from server.services.memory_repository import repository

pytestmark = pytest.mark.skipif(os.name != "posix", reason="private ledger persistence currently requires POSIX")


def manifest(epoch=1):
    return {"format": 1, "instance_id": "00000000-0000-4000-8000-000000000001",
            "deletion_epoch": epoch, "deletions": [
                {"entry_id": f"00000000-0000-4000-8000-{number:012d}", "epoch": number,
                 "content_digest": f"{number:064x}", "scope_kind": "global", "scope_key": ""}
                for number in range(1, epoch + 1)]}


def payload(value):
    return json.dumps(value).encode()


def test_private_bounded_snapshot_is_monotonic_and_idempotent(tmp_path):
    path = tmp_path / ledger.DIRECTORY
    value = manifest()
    assert ledger.read(path, value["instance_id"]) is None
    assert ledger.persist(path, payload(value)) == "current"
    assert path.stat().st_mode & 0o777 == 0o700
    target = path / (value["instance_id"] + ".json")
    assert target.stat().st_mode & 0o777 == 0o600
    assert ledger.read(path, value["instance_id"]) == value
    assert ledger.persist(path, payload(value)) == "current"
    assert ledger.persist(path, payload(manifest(2))) == "current"
    assert ledger.persist(path, payload(value)) == "ahead"
    assert ledger.read(path, value["instance_id"]) == manifest(2)
    assert not list(path.glob(".pending-*"))


@pytest.mark.parametrize("mode", ["same_epoch", "dropped_history"])
def test_conflicting_history_never_replaces_saved_file(tmp_path, mode):
    path = tmp_path / ledger.DIRECTORY
    value = manifest()
    ledger.persist(path, payload(value))
    bad = copy.deepcopy(value) if mode == "same_epoch" else manifest(2)
    bad["deletions"].pop(0)
    with pytest.raises(ValueError, match="deletion_ledger_history_conflict"):
        ledger.persist(path, payload(bad))
    assert ledger.read(path, value["instance_id"]) == value


@pytest.mark.parametrize("slot", ["directory", "snapshot", "lock"])
def test_symlink_slots_are_refused_without_touching_target(tmp_path, slot):
    path = tmp_path / ledger.DIRECTORY
    value = manifest()
    victim = tmp_path / "unrelated"
    if slot == "directory":
        victim.mkdir()
        path.symlink_to(victim, target_is_directory=True)
    else:
        path.mkdir(mode=0o700)
        victim.write_bytes(b"unrelated synthetic content")
        name = value["instance_id"] + ".json" + (".lock" if slot == "lock" else "")
        (path / name).symlink_to(victim)
    with pytest.raises((OSError, ValueError)):
        ledger.persist(path, payload(value))
    if slot == "directory":
        assert list(victim.iterdir()) == []
    else:
        assert victim.read_bytes() == b"unrelated synthetic content"


def test_interrupted_replace_preserves_old_snapshot_and_retry(tmp_path, monkeypatch):
    path = tmp_path / ledger.DIRECTORY
    value = manifest()
    ledger.persist(path, payload(value))

    def fail(*args, **kwargs):
        raise OSError("synthetic disk failure")

    with monkeypatch.context() as patch:
        patch.setattr(ledger.os, "replace", fail)
        with pytest.raises(OSError, match="synthetic disk failure"):
            ledger.persist(path, payload(manifest(2)))
    assert ledger.read(path, value["instance_id"]) == value
    assert not list(path.glob(".pending-*"))
    assert ledger.persist(path, payload(manifest(2))) == "current"


def test_parallel_writers_never_downgrade_snapshot(tmp_path):
    for attempt in range(10):
        path = tmp_path / str(attempt)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda epoch: ledger.persist(path, payload(manifest(epoch))), [3, 1, 4, 2]))
        assert set(results) <= {"current", "ahead"}
        assert ledger.read(path, manifest()["instance_id"]) == manifest(4)


@pytest.mark.parametrize("mode", ["permissions", "hardlink", "oversized"])
def test_unsafe_existing_snapshot_is_not_repaired_by_overwriting(tmp_path, mode):
    path = tmp_path / ledger.DIRECTORY
    value = manifest()
    ledger.persist(path, payload(value))
    target = path / (value["instance_id"] + ".json")
    if mode == "permissions":
        target.chmod(0o644)
    elif mode == "hardlink":
        os.link(target, tmp_path / "other-link")
    else:
        target.write_bytes(b"x" * (ledger.MAX_BYTES + 1))
    original = target.read_bytes()
    with pytest.raises(ValueError):
        ledger.persist(path, payload(manifest(2)))
    assert target.read_bytes() == original


async def test_delete_commit_mirrors_metadata_without_text_or_key(execution_db, tmp_path):
    content = "Synthetic deleted preference for independent persistence"
    async with repository() as repo:
        entry = await repo.create(MemoryWrite(content=content, scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
    assert not (tmp_path / ledger.DIRECTORY).exists()
    async with repository() as repo:
        await repo.delete_entry(entry["id"], entry["version"], MemoryActor(origin="user"))
        assert not (tmp_path / ledger.DIRECTORY).exists()
    async with execution_db() as db:
        snapshot = await db.run_sync(lambda session: export_sync(session.connection()))
        assert await ledger.status(db) == {"status": "current", "database_epoch": 1, "saved_epoch": 1}
        value = ledger.read(ledger.directory(db), decode(snapshot)["instance_id"])
    assert value == decode(snapshot)
    assert content.encode() not in payload(value) and b"digest_key" not in payload(value)
    from server.services import backup
    archive = tmp_path / "backup.zip"
    backup.create(tmp_path, archive, db_path=tmp_path / "execution.db")
    with zipfile.ZipFile(archive) as zipped:
        assert not any(ledger.DIRECTORY in name for name in zipped.namelist())


async def test_rollback_never_persists_uncommitted_deletion(execution_db, tmp_path):
    async with repository() as repo:
        entry = await repo.create(MemoryWrite(content="Synthetic rollback preference", scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
    async with execution_db() as db:
        assert (await ledger.status(db))["status"] == "missing"
    with pytest.raises(RuntimeError):
        async with repository() as repo:
            await repo.delete_entry(entry["id"], entry["version"], MemoryActor(origin="user"))
            raise RuntimeError("synthetic transaction failure")
    assert not (tmp_path / ledger.DIRECTORY).exists()
    async with repository() as repo:
        assert (await repo.present(await repo.get(entry["id"])))["content"] == "Synthetic rollback preference"


async def test_failed_mirror_does_not_undo_delete_and_sync_repairs(execution_db, monkeypatch):
    async with repository() as repo:
        entry = await repo.create(MemoryWrite(content="Synthetic repair preference", scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
    async with execution_db() as db:
        assert await ledger.sync(db) == "current"

    def fail(*args):
        raise OSError("synthetic private filesystem detail")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "persist", fail)
        async with repository() as repo:
            await repo.delete_entry(entry["id"], entry["version"], MemoryActor(origin="user"))
    async with execution_db() as db:
        assert await ledger.status(db) == {"status": "stale", "database_epoch": 1, "saved_epoch": 0}
        assert await ledger.sync(db) == "current"
        assert (await ledger.status(db))["status"] == "current"
    async with repository() as repo:
        assert (await repo.get(entry["id"])).status == "deleted"


async def test_status_detects_ahead_and_corrupt_records(execution_db):
    async with repository() as repo:
        await repo.create(MemoryWrite(content="Synthetic status preference", scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
    async with execution_db() as db:
        value = decode(await db.run_sync(lambda session: export_sync(session.connection())))
        path = ledger.directory(db)
        ahead = copy.deepcopy(value)
        ahead["deletion_epoch"] = 1
        assert ledger.persist(path, payload(ahead)) == "current"
        assert (await ledger.status(db))["status"] == "ahead"
        assert await ledger.sync(db) == "ahead"
        target = path / (value["instance_id"] + ".json")
        target.write_bytes(b"corrupt synthetic file")
        assert (await ledger.status(db))["status"] == "unavailable"
        assert await ledger.sync(db) == "unavailable"
        assert target.read_bytes() == b"corrupt synthetic file"


async def test_legacy_expert_preference_commit_also_updates_ledger(execution_db):
    from server.api.spawns import delete_preference
    from server.db.models import Spawn
    from server.schemas import PreferenceDeleteIn
    from server.services.memory_activation import activate_sync
    from server.services.memory_migration import migrate_legacy_sync

    async with execution_db() as db:
        db.add(Spawn(id=3, name="Synthetic expert", domain_category="content", system_prompt="Synthetic"))
        await db.commit()
    async with execution_db.kw["bind"].begin() as connection:
        await connection.run_sync(migrate_legacy_sync)
        await connection.run_sync(activate_sync)
    content = "Synthetic expert preference"
    async with repository() as repo:
        entry = await repo.create(MemoryWrite(content=content, scope=MemoryScope(kind="expert", id="3")), MemoryActor(origin="user"))
    async with execution_db() as db:
        result = await delete_preference(3, PreferenceDeleteIn(fact=content, entry_id=entry["id"], expected_version=1), db)
        assert result.preferences == []
        assert await ledger.status(db) == {"status": "current", "database_epoch": 1, "saved_epoch": 1}
