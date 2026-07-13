"""Staged-orchestration phase persistence: SpawnPhase table + phase_service."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
import server.db.session as db_session
from server.db.models import Base
from server.services import phase_service


@pytest_asyncio.fixture
async def temp_db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'p.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    return maker


@pytest.mark.asyncio
async def test_set_get_clear_proposing(temp_db):
    await phase_service.set_proposing("conv-a", 4, "research X with angle Y")
    p = await phase_service.get_pending("conv-a")
    assert p is not None and p["spawn_id"] == 4 and p["phase"] == "proposing"
    assert p["direction"] == "research X with angle Y"
    await phase_service.clear("conv-a", 4)
    assert await phase_service.get_pending("conv-a") is None


@pytest.mark.asyncio
async def test_set_proposing_replaces_previous(temp_db):
    await phase_service.set_proposing("conv-b", 1, "d1")
    await phase_service.set_proposing("conv-b", 2, "d2")
    p = await phase_service.get_pending("conv-b")
    assert p["spawn_id"] == 2 and p["direction"] == "d2"  # one pending per conversation
