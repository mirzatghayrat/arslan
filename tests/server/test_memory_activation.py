import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError, OperationalError

from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
from server.db.models import Base, UserFact
from server.services.memory_activation import activate_sync
from server.services.memory_migration import migrate_legacy_sync
from server.services.memory_repository import is_active, repository


async def activate(maker):
    async with maker.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
        await db.run_sync(activate_sync)


async def test_activation_keeps_legacy_identity_and_only_v2_is_writable(execution_db):
    async with execution_db() as db:
        await db.execute(insert(UserFact).values(id=7, content="Old preference", source="manual",
                                                provenance={"source_kind": "manual"}, sensitive=False))
        await db.commit()
    await activate(execution_db)
    assert await is_active()
    async with execution_db() as db:
        assert (await db.execute(text("SELECT id,content FROM user_facts"))).all() == [(7, "Old preference")]
        assert (await db.execute(text("SELECT content FROM legacy_user_facts"))).scalar_one() == "Old preference"
    for statement in ("UPDATE user_facts SET content='wrong' WHERE id=7",
                      "UPDATE legacy_user_facts SET content='wrong' WHERE id=7"):
        with pytest.raises((OperationalError, IntegrityError), match="view|read_only"):
            async with execution_db() as db:
                await db.execute(text(statement))
                await db.commit()
    async with repository() as repo:
        row = await repo.by_compatibility_id("user_facts", 7)
        await repo.revise(row.id, row.version, MemoryWrite(content="New preference",
                         scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
    async with execution_db() as db:
        assert (await db.execute(text("SELECT content FROM user_facts WHERE id=7"))).scalar_one() == "New preference"
        assert (await db.execute(text("SELECT content FROM legacy_user_facts WHERE id=7"))).scalar_one() == "Old preference"


async def test_new_entry_has_legacy_alias_without_legacy_row_and_fts_erases_on_delete(execution_db):
    await activate(execution_db)
    async with repository() as repo:
        row = await repo.create(MemoryWrite(content="Distinctive preference",
                                scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
    async with execution_db() as db:
        assert await db.scalar(text("SELECT COUNT(*) FROM user_facts")) == 1
        assert await db.scalar(text("SELECT COUNT(*) FROM legacy_user_facts")) == 0
        assert await db.scalar(text("SELECT COUNT(*) FROM memory_entries_fts")) == 1
    async with repository() as repo:
        await repo.delete_entry(row["id"], 1, MemoryActor(origin="user"))
    async with execution_db() as db:
        assert await db.scalar(text("SELECT COUNT(*) FROM user_facts")) == 0
        assert await db.scalar(text("SELECT COUNT(*) FROM memory_entries_fts")) == 0


async def test_second_boot_keeps_compatibility_views(execution_db):
    await activate(execution_db)
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(Base.metadata.create_all)
        await db.run_sync(activate_sync)
        kind = (await db.execute(text("SELECT type FROM sqlite_master WHERE name='user_facts'"))).scalar_one()
        assert kind == "view"
