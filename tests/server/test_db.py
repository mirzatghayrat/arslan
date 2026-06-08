"""Database model and session tests."""
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base, Spawn


@pytest_asyncio.fixture
async def session(tmp_path):
    """A throwaway async session backed by a temp-file SQLite DB."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'t.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_insert_and_query_spawn(session):
    spawn = Spawn(
        name="beauty-guru",
        domain_category="content-creator",
        domain_subcategory="xiaohongshu",
        capabilities=["content-generation"],
        system_prompt="You are a beauty expert.",
    )
    session.add(spawn)
    await session.commit()

    result = await session.execute(select(Spawn).where(Spawn.name == "beauty-guru"))
    fetched = result.scalar_one()
    assert fetched.id is not None
    assert fetched.domain_subcategory == "xiaohongshu"
    assert fetched.capabilities == ["content-generation"]
    assert fetched.generation_level == 1


@pytest.mark.asyncio
async def test_wal_mode_enabled(tmp_path):
    from server.db.session import build_engine

    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path/'wal.db'}")
    async with engine.connect() as conn:
        mode = await conn.execute(text("PRAGMA journal_mode"))
        assert mode.scalar_one().lower() == "wal"
    await engine.dispose()
