"""Database model and session tests."""
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base, Toolset


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
async def test_insert_and_query_a_row(session):
    # C7c-5b: the Spawn model went; any model shows the session round-trips.
    session.add(Toolset(key="web", name="Web", description="search", tier="safe", status="wired"))
    await session.commit()

    result = await session.execute(select(Toolset).where(Toolset.key == "web"))
    fetched = result.scalar_one()
    assert fetched.name == "Web"
    assert fetched.status == "wired"


@pytest.mark.asyncio
async def test_wal_mode_enabled(tmp_path):
    from server.db.session import build_engine

    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path/'wal.db'}")
    async with engine.connect() as conn:
        mode = await conn.execute(text("PRAGMA journal_mode"))
        assert mode.scalar_one().lower() == "wal"
    await engine.dispose()
