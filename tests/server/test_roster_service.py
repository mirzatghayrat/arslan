import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
import server.db.session as db_session
from server.db.models import Base, Spawn

@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'r.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with m() as s:
            s.add(Spawn(id=4, name="领英智囊", domain_category="career", capabilities=[], system_prompt="x"))
            await s.commit()
    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m

@pytest.mark.asyncio
async def test_join_idempotent_keeps_via(maker):
    from server.services import roster_service
    first = await roster_service.join("c1", 4, via="routed")
    assert first is True, "first join should return True (newly inserted)"
    second = await roster_service.join("c1", 4, via="invited")
    assert second is False, "idempotent re-add should return False"
    members = await roster_service.list_roster("c1")
    assert len(members) == 1
    assert members[0]["spawn_id"] == 4
    assert members[0]["spawn_name"] == "领英智囊"
    assert members[0]["joined_via"] == "routed"
    assert members[0]["status"] == "idle"

@pytest.mark.asyncio
async def test_kick_and_readd(maker):
    from server.services import roster_service
    await roster_service.join("c1", 4, via="routed")
    assert await roster_service.kick("c1", 4) is True
    assert await roster_service.list_roster("c1") == []
    assert await roster_service.kick("c1", 4) is False
    await roster_service.join("c1", 4, via="routed")
    assert len(await roster_service.list_roster("c1")) == 1

@pytest.mark.asyncio
async def test_status_awaiting_confirm_from_phase(maker, monkeypatch):
    from server.services import roster_service, phase_service
    await roster_service.join("c1", 4, via="routed")
    async def _pending(conv): return {"spawn_id": 4, "phase": "proposing", "direction": "d"}
    monkeypatch.setattr(phase_service, "get_pending", _pending)
    members = await roster_service.list_roster("c1")
    assert members[0]["status"] == "awaiting_confirm"
