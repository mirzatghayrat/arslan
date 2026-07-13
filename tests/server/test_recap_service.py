from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
import server.db.session as db_session
from server.db.models import Base
from server.db.migrations.versions._0024_conversation_events import upgrade_sync


async def test_0024_creates_table(tmp_path):
    e = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'e.db'}")
    async with e.begin() as c:
        await c.run_sync(upgrade_sync)
        names = await c.run_sync(lambda x: set(inspect(x).get_table_names()))
    await e.dispose()
    assert "conversation_events" in names


async def test_log_event_and_read(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'e2.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    from server.services import recap_service
    await recap_service.log_event("conv1", "memory", None, "领域兴趣:半导体")
    await recap_service.log_event(None, "memory", None, "dropped")  # no conv → no-op
    from server.db.models import ConversationEvent
    from sqlalchemy import select
    async with m() as db:
        rows = (await db.execute(select(ConversationEvent))).scalars().all()
    assert len(rows) == 1 and rows[0].kind == "memory" and rows[0].summary == "领域兴趣:半导体"
