import pytest
from sqlalchemy import create_engine, insert, select, text

from arslan.companion.memory import MemoryActor, MemoryError, MemoryScope, MemoryWrite
from server.db.models import (ArslanMessage, ArslanSummary, Base, ConversationContext,
                              MemoryEntry, MemoryRevision, Project, UserFact)
from server.services import backup, personal_context as pc
from server.services.memory_activation import activate_sync
from server.services.memory_migration import migrate_legacy_sync
from server.services.memory_repository import repository
from server.services.memory_restore import apply_pending_guard_sync, mark_restored_sync

USER = MemoryActor(origin="user")


def memory(content="Remembered preference"):
    return MemoryWrite(content=content, scope=MemoryScope(kind="global"), use_policy="cloud_allowed")


async def test_restore_quarantines_revisions_revokes_cloud_and_suppresses_old_sources(execution_db):
    async with repository() as repo:
        saved = await repo.create(memory(), USER)
    async with execution_db() as db:
        db.add(Project(id="p", name="Project"))
        await db.flush()
        db.add(ConversationContext(id="old", project_id="p", cloud_memory_allowed=True, allow_sensitive=True))
        db.add(ArslanMessage(id=301, conversation_id="old", role="user", content="Original conversation"))
        db.add(ArslanSummary(conversation_id="old", summary="Derived memory", up_to_message_id=301))
        await db.commit()
    ctx = pc.TaskMemoryContext(task_id="t", run_id="r", model_is_local=True)
    assert "Remembered preference" in (await pc.assemble(context=ctx)).text
    async with execution_db.kw["bind"].begin() as connection:
        result = await connection.run_sync(mark_restored_sync)
        assert result["quarantined_entries"] == 1
        assert (await connection.run_sync(apply_pending_guard_sync))["quarantined_entries"] == 0
    assert (await pc.assemble(context=ctx)).text == ""
    async with repository() as repo:
        restored = await repo.present(await repo.get(saved["id"]))
        assert restored["version"] == 2 and restored["status"] == "quarantined"
        assert restored["confirmed_at"] is None and restored["use_policy"] == "local_only"
        assert len(await repo.history(saved["id"])) == 2
    async with execution_db() as db:
        assert await db.scalar(select(ArslanSummary.id)) is None
        assert (await db.get(ArslanMessage, 301)).content == "Original conversation"
        context = await db.get(ConversationContext, "old")
        assert not context.cloud_memory_allowed and not context.allow_sensitive and context.version == 2
        assert (await db.get(Project, "p")).status == "archived"
    with pytest.raises(MemoryError, match="memory_source_deleted"):
        async with repository() as repo:
            await repo.create(memory("A paraphrase from restored history"), MemoryActor(origin="extractor", conversation_id="old"))
    # Restoring a backup cannot make stale UI approvals valid. A fresh manual review can.
    with pytest.raises(MemoryError, match="memory_version_conflict"):
        async with repository() as repo:
            await repo.revise(saved["id"], 1, memory(), USER)
    async with repository() as repo:
        await repo.revise(saved["id"], 2, memory(), USER)
    assert "Remembered preference" in (await pc.assemble(context=ctx)).text


def test_legacy_backup_restore_guard_survives_migration_and_keeps_archive_unchanged(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    engine = create_engine(f"sqlite:///{source / 'arslan.db'}")
    with engine.begin() as db:
        Base.metadata.create_all(db)
        db.execute(insert(UserFact).values(id=1, content="Legacy manual preference", source="manual",
                                          sensitive=False, provenance={"source_kind": "manual"}))
        # Simulate a pre-v2 archive, not merely an empty prepared v2 store.
        for table in ("memory_sources", "memory_legacy_map", "memory_suppressions", "memory_migration_reports",
                      "memory_deletions", "memory_entries", "memory_revisions", "memory_store_state"):
            db.exec_driver_sql(f"DROP TABLE {table}")
    engine.dispose()
    archive = tmp_path / "backup.zip"
    backup.create(source, archive)
    original = archive.read_bytes()
    target = tmp_path / "restored"
    report = backup.restore(archive, target)
    assert report["memory_review"]["review_required"] and archive.read_bytes() == original
    restored = create_engine(f"sqlite:///{target / 'arslan.db'}")
    try:
        with restored.begin() as db:
            migrate_legacy_sync(db)
            activate_sync(db)
            entry = db.execute(select(MemoryEntry.__table__)).mappings().one()
            assert entry["status"] == "quarantined" and entry["confirmed_at"] is None
            assert db.execute(text("SELECT content FROM legacy_user_facts WHERE id=1")).scalar() == "Legacy manual preference"
            version = entry["version"]
            migrate_legacy_sync(db)
            assert db.execute(select(MemoryEntry.version)).scalar() == version
    finally:
        restored.dispose()


async def test_active_restore_preserves_deleted_stubs_and_tombstones(execution_db):
    async with repository() as repo:
        saved = await repo.create(memory(), USER)
        await repo.delete_entry(saved["id"], saved["version"], USER)
    async with execution_db.kw["bind"].begin() as connection:
        await connection.run_sync(migrate_legacy_sync)
        await connection.run_sync(activate_sync)
        result = await connection.run_sync(mark_restored_sync)
        assert result["quarantined_entries"] == 0
    async with execution_db() as db:
        assert (await db.get(MemoryEntry, saved["id"])).status == "deleted"
        assert not any((await db.execute(select(MemoryRevision.content))).scalars())
    with pytest.raises(MemoryError, match="memory_previously_deleted"):
        async with repository() as repo:
            await repo.create(memory(), USER)
