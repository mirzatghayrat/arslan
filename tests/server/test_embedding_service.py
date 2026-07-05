"""Embedding provider layer: codec, preference-order resolution, API provider."""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'e.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    anyio.run(_seed)
    return m


def test_vec_blob_roundtrip():
    from server.services import embedding_service as es
    vec = [0.1, -2.5, 3.25, 0.0]
    out = es.blob_to_vec(es.vec_to_blob(vec))
    assert out == pytest.approx(vec)


def test_active_provider_none_when_unconfigured(maker):
    from server.services import embedding_service as es
    assert anyio.run(es.active_provider) is None


def test_active_provider_preference_order(maker, monkeypatch):
    """zhipu 配了就选 zhipu embedding-3。"""
    from server.services import embedding_service as es
    from server import crypto
    from server.db.models import ProviderConfig
    async def _run(provider):
        async with maker() as s:
            s.add(ProviderConfig(label="t", provider=provider, model="x",
                                 api_key=crypto.encrypt("sk-test-12345678"), is_primary=True))
            await s.commit()
        return await es.active_provider()
    p = anyio.run(_run, "zhipu")
    assert p is not None and p.model_id == "embedding-3"
    assert "bigmodel.cn" in p.base_url


def test_active_provider_skips_non_embedding_provider(maker):
    from server.services import embedding_service as es
    from server import crypto
    from server.db.models import ProviderConfig
    async def _run():
        async with maker() as s:
            s.add(ProviderConfig(label="t", provider="deepseek", model="deepseek-chat",
                                 api_key=crypto.encrypt("sk-test-12345678"), is_primary=True))
            await s.commit()
        return await es.active_provider()
    assert anyio.run(_run) is None
