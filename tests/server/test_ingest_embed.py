"""Ingest: collection targets + best-effort embedding on ingest."""
import anyio
import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Collection, Spawn


class FakeProvider:
    model_id = "fake-embed-1"
    def __init__(self):
        self.calls = 0
    async def embed(self, texts):
        self.calls += 1
        return [[1.0, 0.0, float(len(t))] for t in texts]


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'i.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.exec_driver_sql(
                "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(text)")
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
        async with m() as s:
            s.add(Spawn(id=1, name="s", domain_category="c", system_prompt="p"))
            s.add(Collection(id=9, name="资料库"))
            await s.commit()
    anyio.run(_seed)
    return m


def test_ingest_into_collection(maker):
    from server.services import ingest
    n = anyio.run(lambda: ingest.ingest_text(None, "a.txt", "共享资料内容", collection_id=9))
    assert n == 1
    async def _check():
        async with maker() as s:
            return (await s.execute(sa_text(
                "SELECT spawn_id, collection_id FROM knowledge_chunks"))).one()
    assert anyio.run(_check) == (None, 9)


def test_ingest_requires_exactly_one_target(maker):
    from server.services import ingest
    with pytest.raises(ValueError):
        anyio.run(lambda: ingest.ingest_text(1, "a", "x", collection_id=9))
    with pytest.raises(ValueError):
        anyio.run(lambda: ingest.ingest_text(None, "a", "x"))


def test_ingest_embeds_when_provider_available(maker, monkeypatch):
    from server.services import embedding_service, ingest
    provider = FakeProvider()
    async def _fake_active():
        return provider
    monkeypatch.setattr(embedding_service, "active_provider", _fake_active)
    long_text = "深井内容。" * 400  # chunk_text splits at ~800 chars → multiple chunks
    n = anyio.run(lambda: ingest.ingest_text(1, "b.txt", long_text))
    assert n > 1
    assert provider.calls == 1  # one batch call across all chunks, not per-chunk
    async def _check():
        async with maker() as s:
            return (await s.execute(sa_text(
                "SELECT embedding, embedding_model FROM knowledge_chunks WHERE source='b.txt'"))).all()
    rows = anyio.run(_check)
    assert len(rows) == n
    for blob, model in rows:
        assert model == "fake-embed-1" and blob is not None
        assert embedding_service.blob_to_vec(blob)[0] == pytest.approx(1.0)


def test_ingest_survives_embed_failure(maker, monkeypatch):
    """Provider blows up → chunks land with NULL embedding (FTS-only)."""
    from server.services import embedding_service, ingest
    class Boom:
        model_id = "boom"
        async def embed(self, texts):
            raise RuntimeError("api down")
    async def _fake_active():
        return Boom()
    monkeypatch.setattr(embedding_service, "active_provider", _fake_active)
    n = anyio.run(lambda: ingest.ingest_text(1, "c.txt", "内容"))
    assert n == 1
    async def _check():
        async with maker() as s:
            return (await s.execute(sa_text(
                "SELECT embedding FROM knowledge_chunks WHERE source='c.txt'"))).one()[0]
    assert anyio.run(_check) is None
