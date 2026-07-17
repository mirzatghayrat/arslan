"""Test suite for mcp_server_enabled setting."""
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base
from server.services import settings_service


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_default_is_false(db):
    assert await settings_service.mcp_server_enabled(db) is False


async def test_enabled_only_on_explicit_true(db):
    await settings_service.update_settings(db, {"mcp_server_enabled": True})
    assert await settings_service.mcp_server_enabled(db) is True
    await settings_service.update_settings(db, {"mcp_server_enabled": False})
    assert await settings_service.mcp_server_enabled(db) is False


async def test_roundtrips_through_get_settings(db):
    await settings_service.update_settings(db, {"mcp_server_enabled": True})
    out = await settings_service.get_settings(db)
    # get_settings returns the plain string; SettingsOut coerces it to bool
    from server.schemas import SettingsOut
    assert SettingsOut(**out).mcp_server_enabled is True
