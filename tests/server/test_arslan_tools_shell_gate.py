"""Arslan's run_command tool is gated on the opt-in orchestrator_shell_enabled setting."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'gate.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_run_command_absent_when_shell_off(maker):
    from server.orchestrator import arslan

    tools = await arslan._arslan_tools()
    assert not any(t["key"] == "run_command" for t in tools)


@pytest.mark.asyncio
async def test_run_command_present_when_shell_on(maker):
    from server.orchestrator import arslan
    from server.services import settings_service

    async with maker() as s:
        await settings_service.update_settings(s, {"orchestrator_shell_enabled": "true"})
    tools = await arslan._arslan_tools()
    assert any(t["key"] == "run_command" for t in tools)
