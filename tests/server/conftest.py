"""Shared fixtures for server tests."""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base
from server.db.session import get_session


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async HTTP client with an isolated temp-file SQLite DB."""
    import os

    os.environ["ARSLAN_TEST_ROUTES"] = "1"

    from server.main import create_app

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'app.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_session():
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await engine.dispose()
