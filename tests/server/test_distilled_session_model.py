from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


async def test_distilled_session_roundtrip(tmp_path):
    from server.db.models import Base, DistilledSession
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'d.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with m() as s:
        s.add(DistilledSession(conversation_id="c1", spawn_id=3))
        await s.commit()
    async with m() as s:
        rows = (await s.execute(select(DistilledSession).where(
            DistilledSession.conversation_id == "c1", DistilledSession.spawn_id == 3))).scalars().all()
    assert len(rows) == 1
