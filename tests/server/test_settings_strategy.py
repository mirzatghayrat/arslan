import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base
from server.services import settings_service


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'strat.db'}")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_strategy_roundtrips(db):
    await settings_service.update_settings(db, {"llm_strategy": "cost"})
    assert (await settings_service.get_settings(db))["llm_strategy"] == "cost"


@pytest.mark.asyncio
async def test_strategy_default_absent(db):
    """When not set, get_settings should not include llm_strategy (or return empty string)."""
    result = await settings_service.get_settings(db)
    # When not stored, the key should either be absent or empty — not "cost" etc.
    assert result.get("llm_strategy", "") == ""
