"""orchestrator_shell_enabled + shell_confirm_policy setting helpers."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'shell.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_shell_on_by_default_and_off_only_when_switched_off(maker):
    # 0.1.48: the terminal is on unless the user switches it off.
    from server.services import settings_service

    async with maker() as s:
        assert await settings_service.shell_enabled(s) is True
    async with maker() as s:
        await settings_service.update_settings(s, {"orchestrator_shell_enabled": "false"})
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
async def test_confirm_policy_defaults_to_asking_only_for_risky(maker):
    # 0.1.48: harmless commands run; the rest show a card.
    from server.services import settings_service

    async with maker() as s:
        assert await settings_service.shell_confirm_policy(s) == "ask_risky"


@pytest.mark.asyncio
async def test_asking_for_everything_is_an_explicit_choice_that_persists(maker):
    from server.services import settings_service

    async with maker() as s:
        await settings_service.update_settings(s, {"shell_confirm_policy": "ask_all"})
    async with maker() as s:
        assert await settings_service.shell_confirm_policy(s) == "ask_all"
    async with maker() as s:
        await settings_service.update_settings(s, {"shell_confirm_policy": "garbage"})
    async with maker() as s:
        assert await settings_service.shell_confirm_policy(s) == "ask_risky"
