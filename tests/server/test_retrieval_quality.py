"""Retrieval quality: vector-route relevance floor (_MIN_COSINE) + rerank()."""
import logging

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, KnowledgeChunk, Spawn
from server.services import embedding_service, knowledge
from server.services.knowledge import rerank


def test_rerank_orders_by_token_overlap():
    cands = [("a", "completely unrelated text"), ("b", "cat food pricing table")]
    out = rerank("cat food", cands)
    assert out[0][0] == "b"                                # 重叠多的顶上来


def test_rerank_stable_on_zero_overlap():
    cands = [("a", "纯中文甲"), ("b", "纯中文乙")]
    assert rerank("query", cands) == cands                 # 零重叠保持 RRF 原序


def test_rerank_empty():
    assert rerank("q", []) == []


class _AlignedProvider:
    """Always returns a fixed query vector: cosine=1.0 with the 'aligned' chunk,
    cosine=-1.0 with the 'opposite' chunk. Distinct model_id so this test's rows
    are the only ones visible to _vector_route's embedding_model filter."""
    model_id = "fake-embed-ortho"

    async def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


@pytest_asyncio.fixture
async def min_cosine_db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'mc.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(text)")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    async with m() as s:
        s.add(Spawn(id=1, name="甲", domain_category="c", system_prompt="p"))
        await s.flush()
        # kept: cosine(query, vec) = 1.0 (>= _MIN_COSINE=0.15) — must survive.
        s.add(KnowledgeChunk(
            id=500, spawn_id=1, source="aligned.txt", chunk_index=0,
            text="aligned relevant chunk",
            embedding=embedding_service.vec_to_blob([1.0, 0.0, 0.0]),
            embedding_model="fake-embed-ortho"))
        # dropped: cosine(query, vec) = -1.0 (< _MIN_COSINE) — must be filtered.
        s.add(KnowledgeChunk(
            id=501, spawn_id=1, source="opposite.txt", chunk_index=0,
            text="opposite irrelevant chunk",
            embedding=embedding_service.vec_to_blob([-1.0, 0.0, 0.0]),
            embedding_model="fake-embed-ortho"))
        # No FTS rows inserted for either chunk — the probe query below shares
        # no tokens with them, so only the vector route contributes candidates
        # and the assertion below is unambiguously about _MIN_COSINE filtering.
        await s.commit()
    return m


async def test_min_cosine_filters_and_logs(min_cosine_db, monkeypatch, caplog):
    """_vector_route must drop below-threshold neighbors from the returned scope
    and leave a debug trace (not a silent drop) — per the round's rule that
    skips must leave a trace."""
    async def _fake_active():
        return _AlignedProvider()
    monkeypatch.setattr(embedding_service, "active_provider", _fake_active)
    caplog.set_level(logging.DEBUG, logger="server.services.knowledge")

    out = await knowledge.retrieve_scoped("probe query text", spawn_id=1, k=10)
    texts = [t for _, t in out]

    assert any("aligned relevant chunk" in t for t in texts)          # cos=1.0 kept
    assert not any("opposite irrelevant chunk" in t for t in texts)   # cos=-1.0 dropped
    assert any("_MIN_COSINE" in rec.message and "dropped" in rec.message
               for rec in caplog.records)
