import anyio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _maker(tmp_path):
    from server.db.models import Base
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    anyio.run(_init)
    return m


def test_distill_enabled_defaults_true(tmp_path):
    from server.services import settings_service
    m = _maker(tmp_path)
    async def _run():
        async with m() as s:
            return await settings_service.distill_enabled(s)
    assert anyio.run(_run) is True


def test_distill_toggle_roundtrip(tmp_path):
    from server.services import settings_service
    m = _maker(tmp_path)
    async def _run():
        async with m() as s:
            await settings_service.update_settings(s, {"distill_on_session_end": False})
        async with m() as s:
            enabled = await settings_service.distill_enabled(s)
            out = await settings_service.get_settings(s)
        return enabled, out
    enabled, out = anyio.run(_run)
    assert enabled is False
    assert out["distill_on_session_end"] == "False"  # stored as str(bool)
