"""orchestrator_shell_enabled + shell_confirm_policy setting helpers."""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'shell.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_setup)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_shell_disabled_by_default(maker):
    from server.services import settings_service

    async with maker() as s:
        assert await settings_service.shell_enabled(s) is False


@pytest.mark.asyncio
async def test_shell_enabled_when_true(maker):
    from server.services import settings_service

    async with maker() as s:
        await settings_service.update_settings(s, {"orchestrator_shell_enabled": "true"})
    async with maker() as s:
        assert await settings_service.shell_enabled(s) is True


@pytest.mark.asyncio
async def test_confirm_policy_defaults_ask_all(maker):
    from server.services import settings_service

    async with maker() as s:
        assert await settings_service.shell_confirm_policy(s) == "ask_all"


@pytest.mark.asyncio
async def test_confirm_policy_ask_risky_persists(maker):
    from server.services import settings_service

    async with maker() as s:
        await settings_service.update_settings(s, {"shell_confirm_policy": "ask_risky"})
    async with maker() as s:
        assert await settings_service.shell_confirm_policy(s) == "ask_risky"
