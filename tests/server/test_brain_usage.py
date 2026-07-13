import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.services import brain_usage


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'brain_usage.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_record_upserts_and_increments(maker):
    await brain_usage.record("material", "material:coll:1:okx.pdf", used_ref="conv-a")
    await brain_usage.record("material", "material:coll:1:okx.pdf", used_ref="conv-b")
    mp = await brain_usage.usage_map([("material", "material:coll:1:okx.pdf")])
    row = mp[("material", "material:coll:1:okx.pdf")]
    assert row["usage_count"] == 2
    assert row["last_used_ref"] == "conv-b"
    assert row["last_used_at"] is not None


@pytest.mark.asyncio
async def test_usage_map_missing_is_absent(maker):
    mp = await brain_usage.usage_map([("profile", "fact:999999")])
    assert ("profile", "fact:999999") not in mp


@pytest.mark.asyncio
async def test_record_fail_open(maker, monkeypatch):
    class _Boom:
        def __call__(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(brain_usage.db_session, "AsyncSessionLocal", _Boom())
    await brain_usage.record("learning", "learning:1", used_ref="x")  # must not raise
