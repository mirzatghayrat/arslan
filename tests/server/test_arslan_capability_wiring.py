"""A-wiring: list_my_capabilities is offered to Arslan, and the prompt points at it."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


@pytest_asyncio.fixture
async def db(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'w.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_arslan_tools_includes_list_my_capabilities(db):
    from server.orchestrator import arslan
    tools = await arslan._arslan_tools()
    assert any(t["key"] == "list_my_capabilities" for t in tools)


def test_capability_self_prompt_points_at_tool():
    from server.orchestrator import arslan
    assert "list_my_capabilities" in arslan._CAPABILITY_SELF
