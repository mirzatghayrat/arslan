"""retrieve_scoped: the ONLY retrieval gate. Memory v2 scope (the turn project's collections) + RRF hybrid."""
import pytest_asyncio
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Collection, KnowledgeChunk, Spawn, SpawnCollection
from server.services import embedding_service
from server.services import personal_context as pc

from .v2_retrieval import context, project


class FakeProvider:
    """Deterministic 2-d embeddings: '猫' → [1,0]; '狗' → [0,1]; queries likewise."""
    model_id = "fake-embed-3"
    async def embed(self, texts):
        return [[1.0, 0.0] if "猫" in t else [0.0, 1.0] for t in texts]


async def _add_chunk(s, cid, *, spawn_id=None, collection_id=None, source, text, vec=None):
    row = KnowledgeChunk(id=cid, spawn_id=spawn_id, collection_id=collection_id,
                         source=source, chunk_index=0, text=text,
                         embedding=embedding_service.vec_to_blob(vec) if vec else None,
                         embedding_model="fake-embed-3" if vec else None)
    s.add(row)
    await s.flush()
    await s.execute(sa_text(
        "INSERT INTO knowledge_chunks_fts (rowid, text) VALUES (:r, :t)"),
        {"r": cid, "t": text})


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'r.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(text)")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    async with m() as s:
        s.add(Spawn(id=1, name="甲", domain_category="c", system_prompt="p"))
        s.add(Spawn(id=2, name="乙", domain_category="c", system_prompt="p"))
        s.add(Collection(id=10, name="绑定库"))
        s.add(Collection(id=11, name="别人的库"))
        s.add(SpawnCollection(spawn_id=1, collection_id=10))
        s.add(project([10]))                          # the turn's project holds collection 10 only
        # spawn-1 well / bound collection-10 / unbound collection-11 / spawn-2 well
        await _add_chunk(s, 100, spawn_id=1, source="well.txt", text="猫粮 深井资料", vec=[1, 0])
        await _add_chunk(s, 101, collection_id=10, source="shared.pdf", text="猫粮 共享资料", vec=[1, 0])
        await _add_chunk(s, 102, collection_id=11, source="other.pdf", text="猫粮 未绑定资料", vec=[1, 0])
        await _add_chunk(s, 103, spawn_id=2, source="w2.txt", text="猫粮 别的分身深井", vec=[1, 0])
        await s.commit()
    return m


def _texts(chunks):
    return [t for _, t in chunks]


async def _retrieve(query, *, ctx=None, spawn_id=None, k=10):
    from server.services import knowledge
    with pc.bind(ctx or context()):
        return await knowledge.retrieve_scoped(query, spawn_id=spawn_id, k=k)


async def test_a_turn_sees_its_projects_collections_only_never_wells(maker):
    texts = _texts(await _retrieve("猫粮"))
    assert any("共享资料" in t for t in texts)          # collection 10, in the project
    assert not any("未绑定" in t for t in texts)        # collection 11, not in it
    assert not any("深井" in t for t in texts)          # an expert's own well: never


async def test_no_context_no_project_or_another_expert_retrieves_nothing(maker):
    from server.services import knowledge
    assert await knowledge.retrieve_scoped("猫粮", spawn_id=None, k=10) == []          # no context bound
    assert await _retrieve("猫粮", ctx=context(project_id=None)) == []                 # no project
    assert await _retrieve("猫粮", spawn_id=1) == []                                   # not this turn's expert
    assert await _retrieve("猫粮", ctx=context(model_is_local=False, cloud_memory_allowed=False)) == []


async def test_vector_route_merges_semantic_hit(maker, monkeypatch):
    """FTS 完全不命中(查询词不同)时,向量路仍召回语义近邻。"""
    async def _fake_active():
        return FakeProvider()
    monkeypatch.setattr(embedding_service, "active_provider", _fake_active)
    texts = _texts(await _retrieve("猫咪吃什么", k=5))
    assert any("共享资料" in t for t in texts)


async def test_fts_only_without_provider(maker):
    assert _texts(await _retrieve("猫粮", k=5)) == ["猫粮 共享资料"]   # FTS alone, inside the scope


async def test_empty_vector_scope_skips_query_embedding(maker, monkeypatch):
    """Scope 内没有一条(当前模型的)向量 ⇒ 不得为查询白付一次 embedding 调用。"""
    class CountingProvider(FakeProvider):
        calls = 0
        async def embed(self, texts):
            CountingProvider.calls += 1
            return await super().embed(texts)

    async def _fake_active():
        return CountingProvider()
    monkeypatch.setattr(embedding_service, "active_provider", _fake_active)
    async with maker() as s:
        s.add(Collection(id=12, name="新库"))
        s.add(project([12], project_id="p-new"))
        await s.flush()
        await _add_chunk(s, 200, collection_id=12, source="new.txt", text="猫粮 新库无向量")
        await s.commit()
    out = await _retrieve("猫粮", ctx=context(project_id="p-new"), k=5)
    assert CountingProvider.calls == 0          # 没白付 embedding 网络调用
    assert any("新库无向量" in t for t in _texts(out))   # FTS 路照常召回


async def test_without_cloud_consent_the_query_is_never_embedded_by_an_api(maker, monkeypatch):
    """A local turn without cloud-memory consent may use only an installed local embedder. Resolving the
    default API provider would send the query out without consent."""
    from server.services import local_embedding

    class CountingProvider(FakeProvider):
        calls = 0
        async def embed(self, texts):
            CountingProvider.calls += 1
            return await super().embed(texts)

    async def _fake_active():
        return CountingProvider()
    monkeypatch.setattr(embedding_service, "active_provider", _fake_active)
    monkeypatch.setattr(local_embedding, "provider_if_ready", lambda: None)
    out = await _retrieve("猫咪吃什么", ctx=context(cloud_memory_allowed=False), k=5)
    assert CountingProvider.calls == 0 and out == []      # FTS misses this query; no API embedding


def test_rrf_merge_dedups_and_ranks():
    from server.services.knowledge import rrf_merge
    # id=7 在两路都第一 → 融合后必第一;id=8/9 各只在一路
    assert rrf_merge([[7, 8], [7, 9]], k=3)[0] == 7
    assert set(rrf_merge([[7, 8], [7, 9]], k=3)) == {7, 8, 9}


def test_knowledge_block_carries_source():
    from server.services.knowledge import knowledge_block
    block = knowledge_block([("合同.pdf", "第三条:...")])
    assert "[合同.pdf]" in block and "第三条" in block
    assert knowledge_block([]) == ""
