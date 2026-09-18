"""Tests for startup backfill wiring (A3b).

Verifies that:
1. upgrade_sync populates a primary provider_configs row from legacy settings keys.
2. server/main.py's lifespan wires the backfill call after create_all.
"""
import sqlalchemy as sa
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from server import crypto
from server.db.models import Base
from server.db.migrations.versions._0006_provider_configs import upgrade_sync


async def test_startup_backfill_populates_primary_from_legacy_key():
    eng = create_async_engine("sqlite+aiosqlite://")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # seed a legacy key the way the running app would have it
        await conn.execute(
            sa.text(
                "INSERT INTO settings (key, value) VALUES "
                "('llm_provider','deepseek'),('llm_model','deepseek-chat'),"
                "('llm_base_url',''),('llm_api_key',:k)"
            ),
            {"k": crypto.encrypt("sk-legacy-99999")},
        )
        await conn.run_sync(upgrade_sync)  # <-- the startup wiring under test
        rows = (
            await conn.execute(
                sa.text("SELECT provider, is_primary, api_key FROM provider_configs")
            )
        ).all()
    await eng.dispose()

    assert len(rows) == 1
    assert rows[0][0] == "deepseek" and rows[0][1] in (1, True)
    assert crypto.decrypt(rows[0][2]) == "sk-legacy-99999"


async def test_main_lifespan_calls_backfill(monkeypatch, tmp_path):
    """Exercise normal lifespan delegation and shared boot callback order."""
    from contextlib import asynccontextmanager
    from dataclasses import replace
    from server import main, config, token_bootstrap
    from server.db.migrations import runner
    from server.services import storage_boot, crypto_boot, memory_activation

    callbacks = []
    class Connection:
        async def run_sync(self, callback):
            callbacks.append(callback)

    class Engine:
        @asynccontextmanager
        async def begin(self):
            yield Connection()

    engine = Engine()
    initialize = storage_boot.initialize
    class ReachedBoot(Exception):
        pass

    async def observe(actual):
        assert actual is engine
        await initialize(actual)
        raise ReachedBoot  # Stop before normal background services can start.

    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(storage_boot, "initialize", observe)
    monkeypatch.setattr(token_bootstrap, "bootstrap_api_token", lambda settings: None)
    monkeypatch.setattr(main, "_validate_settings", lambda *args, **kwargs: None)
    monkeypatch.setattr(config, "settings", replace(config.settings, data_dir=tmp_path,
                                                   db_path=str(tmp_path / "test.db"),
                                                   spawns_dir=tmp_path / "spawns"))
    with pytest.raises(ReachedBoot):
        async with main.lifespan(main.app):
            pytest.fail("must stop before serving")

    assert callbacks == [Base.metadata.create_all, runner.apply_pending,
                         crypto_boot.resolve_and_adopt_salt,
                         crypto_boot.migrate_legacy_ciphertext, memory_activation.activate_sync]
    assert runner.MIGRATIONS[0][0] == "0006", (
        "the _0006 provider_configs backfill must stay first in the runner registry "
        "so it still runs at boot"
    )
