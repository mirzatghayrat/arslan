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


async def test_real_startup_activates_memory_before_seeders_or_background_work(execution_db, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from server import auth, config, main, token_bootstrap
    from server.registry import seeder
    from server.services import crypto_boot, native_locale

    class BeforeBackgroundWork(Exception):
        pass

    async def stop_after_database():
        raise BeforeBackgroundWork

    async def no_locale_work(_session):
        pass

    monkeypatch.setattr(main, "engine", execution_db.kw["bind"])
    monkeypatch.setattr(config, "settings", SimpleNamespace(db_path=tmp_path / "unused.db", spawns_dir=tmp_path / "spawns"))
    monkeypatch.setattr(token_bootstrap, "bootstrap_api_token", lambda _: None)
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-only")
    monkeypatch.setattr(main, "_validate_settings", lambda *a, **k: None)
    monkeypatch.setattr(main, "_log_data_location", lambda _: None)
    monkeypatch.setattr(crypto_boot, "resolve_and_adopt_salt", lambda _: None)
    monkeypatch.setattr(crypto_boot, "migrate_legacy_ciphertext", lambda _: None)
    monkeypatch.setattr(native_locale, "sync", no_locale_work)
    monkeypatch.setattr(seeder, "seed_registry", stop_after_database)
    async with execution_db() as db:
        await db.execute(insert(UserFact).values(id=700, content="Startup legacy preference", source="manual",
                                                sensitive=False, provenance={"source_kind": "manual"}))
        await db.commit()
    for _ in range(2):
        with pytest.raises(BeforeBackgroundWork):
            async with main.lifespan(None):
                pytest.fail("must stop before background services")
        assert await is_active()
        async with execution_db() as db:
            from server.services import memory_deletion_ledger
            assert (await memory_deletion_ledger.status(db))["status"] == "current"
            assert await db.scalar(text("SELECT content FROM legacy_user_facts WHERE id=700")) == "Startup legacy preference"
            assert await db.scalar(text("SELECT type FROM sqlite_master WHERE name='user_facts'")) == "view"


async def test_activation_transaction_failure_retains_prepared_legacy_tables(execution_db):
    async with execution_db() as db:
        await db.execute(insert(UserFact).values(id=701, content="Rollback recovery preference", source="manual",
                                                sensitive=False, provenance={"source_kind": "manual"}))
        await db.commit()
    async with execution_db.kw["bind"].begin() as connection:
        await connection.run_sync(migrate_legacy_sync)
    with pytest.raises(RuntimeError, match="synthetic startup failure"):
        async with execution_db.kw["bind"].begin() as connection:
            await connection.run_sync(activate_sync)
            raise RuntimeError("synthetic startup failure")
    async with execution_db() as db:
        assert await db.scalar(text("SELECT phase FROM memory_store_state WHERE id=1")) == "prepared"
        assert await db.scalar(text("SELECT type FROM sqlite_master WHERE name='user_facts'")) == "table"
        assert await db.scalar(text("SELECT content FROM user_facts WHERE id=701")) == "Rollback recovery preference"
    await activate(execution_db)
    assert await is_active()
