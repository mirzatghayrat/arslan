"""embed_missing backfill: fills NULL/stale-model vectors, reports progress."""
import anyio
import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, KnowledgeChunk, Spawn


class FakeProvider:
    model_id = "fake-embed-2"
    def __init__(self):
        self.calls = 0
    async def embed(self, texts):
        self.calls += 1
        return [[0.5, 0.5] for _ in texts]


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'bf.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
        async with m() as s:
            s.add(Spawn(id=1, name="s", domain_category="c", system_prompt="p"))
            for i in range(3):
                s.add(KnowledgeChunk(spawn_id=1, source="a", chunk_index=i, text=f"块{i}"))
            s.add(KnowledgeChunk(spawn_id=1, source="b", chunk_index=0, text="旧模型",
                                 embedding=b"\x00\x00\x80?", embedding_model="stale-model"))
            await s.commit()
    anyio.run(_seed)
    return m


def test_embed_missing_backfills_null_and_stale(maker, monkeypatch):
    from server.services import embedding_service as es
    provider = FakeProvider()
    async def _fake_active():
        return provider
    monkeypatch.setattr(es, "active_provider", _fake_active)
    done = anyio.run(lambda: es.embed_missing(batch_size=2))
    assert done == 4  # 3 NULL + 1 stale-model
    assert provider.calls == 2  # batch_size=2 → ceil(4/2) batches, batched not per-row
    async def _check():
        async with maker() as s:
            return (await s.execute(sa_text(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding_model = 'fake-embed-2'"
            ))).scalar_one()
    assert anyio.run(_check) == 4
    st = es.reindex_status()
    assert st["running"] is False and st["done"] == 4


def test_embed_missing_noop_without_provider(maker):
    from server.services import embedding_service as es
    assert anyio.run(lambda: es.embed_missing()) == 0


def test_embed_missing_short_vector_response_terminates(maker, monkeypatch):
    """Provider returns fewer vectors than texts → error recorded, no infinite
    loop, running reset. Without the count guard the un-updated rows keep
    matching the predicate forever."""
    from server.services import embedding_service as es
    class ShortProvider:
        model_id = "short-embed"
        def __init__(self):
            self.calls = 0
        async def embed(self, texts):
            self.calls += 1
            return [[0.1, 0.2] for _ in texts[:-1]]  # always one vector short
    provider = ShortProvider()
    async def _fake_active():
        return provider
    monkeypatch.setattr(es, "active_provider", _fake_active)
    done = anyio.run(lambda: es.embed_missing(batch_size=2))
    assert done == 0  # guard raises before any row of the batch is committed
    assert provider.calls == 1  # first bad batch aborts the run
    st = es.reindex_status()
    assert st["running"] is False
    assert st["error"] and "vectors" in st["error"]


def test_embed_missing_partial_progress_honest_on_later_batch_failure(maker, monkeypatch):
    """First batch succeeds and commits; second batch trips the short-vector
    guard. `done` must reflect the committed first batch (not 0, not all),
    the error must be recorded, running must reset, and only the first
    batch's rows may have persisted embeddings — proving progress reporting
    tells the truth about partial work rather than collapsing to all-or-nothing."""
    from server.services import embedding_service as es

    class FlakyProvider:
        model_id = "flaky-embed"
        def __init__(self):
            self.calls = 0
        async def embed(self, texts):
            self.calls += 1
            if self.calls == 1:
                return [[0.9, 0.9] for _ in texts]  # batch 1: succeeds fully
            return [[0.1, 0.2] for _ in texts[:-1]]  # batch 2: one vector short

    provider = FlakyProvider()
    async def _fake_active():
        return provider
    monkeypatch.setattr(es, "active_provider", _fake_active)
    done = anyio.run(lambda: es.embed_missing(batch_size=2))
    assert done == 2  # exactly batch 1's committed rows — not 0, not all 4
    assert provider.calls == 2
    st = es.reindex_status()
    assert st["running"] is False
    assert st["done"] == 2
    assert st["error"] and "vectors" in st["error"]

    async def _check():
        async with maker() as s:
            embedded = (await s.execute(sa_text(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding_model = 'flaky-embed'"
            ))).scalar_one()
            still_pending = (await s.execute(sa_text(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE "
                "embedding IS NULL OR embedding_model IS NULL OR embedding_model != 'flaky-embed'"
            ))).scalar_one()
            return embedded, still_pending
    embedded, still_pending = anyio.run(_check)
    assert embedded == 2  # batch 1's rows persisted
    assert still_pending == 2  # batch 2's rows (1 NULL + 1 stale-model) untouched
