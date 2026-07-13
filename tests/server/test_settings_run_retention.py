from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


async def _maker(tmp_path):
    from server.db.models import Base
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return m


async def test_run_debug_retention_days_defaults_30(tmp_path):
    from server.services import settings_service
    m = await _maker(tmp_path)
    async with m() as s:
        assert await settings_service.run_debug_retention_days(s) == 30


async def test_run_debug_retention_days_roundtrip(tmp_path):
    from server.services import settings_service
    m = await _maker(tmp_path)
    async with m() as s:
        await settings_service._set_raw(s, "run_debug_retention_days", "7")
        await s.commit()
    async with m() as s:
        assert await settings_service.run_debug_retention_days(s) == 7
