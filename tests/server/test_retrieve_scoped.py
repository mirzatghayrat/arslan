"""retrieve_scoped: the ONLY retrieval gate. Partition invariants + RRF hybrid."""
import anyio
import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Collection, KnowledgeChunk, Spawn, SpawnCollection
from server.services import embedding_service


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


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'r.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
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
            # spawn-1 well / bound collection-10 / unbound collection-11 / spawn-2 well
            await _add_chunk(s, 100, spawn_id=1, source="well.txt", text="猫粮 深井资料", vec=[1, 0])
            await _add_chunk(s, 101, collection_id=10, source="shared.pdf", text="猫粮 共享资料", vec=[1, 0])
            await _add_chunk(s, 102, collection_id=11, source="other.pdf", text="猫粮 未绑定资料", vec=[1, 0])
            await _add_chunk(s, 103, spawn_id=2, source="w2.txt", text="猫粮 别的分身深井", vec=[1, 0])
            await s.commit()
    anyio.run(_seed)
    return m


def _texts(chunks):
    return [t for _, t in chunks]


def test_partition_spawn_sees_well_and_bound_only(maker):
    from server.services import knowledge
    out = anyio.run(lambda: knowledge.retrieve_scoped("猫粮", spawn_id=1, k=10))
    texts = _texts(out)
    assert any("深井资料" in t for t in texts)
    assert any("共享资料" in t for t in texts)
    assert not any("未绑定" in t for t in texts)      # 未绑定 collection 不可见
    assert not any("别的分身" in t for t in texts)     # 他人深井不可见


def test_partition_arslan_sees_all_collections_never_wells(maker):
    from server.services import knowledge
    out = anyio.run(lambda: knowledge.retrieve_scoped("猫粮", spawn_id=None, k=10))
    texts = _texts(out)
    assert any("共享资料" in t for t in texts)
    assert any("未绑定资料" in t for t in texts)       # 主脑看全部共享库
    assert not any("深井" in t for t in texts)         # 永不碰深井


def test_vector_route_merges_semantic_hit(maker, monkeypatch):
    """FTS 完全不命中(查询词不同)时,向量路仍召回语义近邻。"""
    from server.services import knowledge
    async def _fake_active():
        return FakeProvider()
    monkeypatch.setattr(embedding_service, "active_provider", _fake_active)
    out = anyio.run(lambda: knowledge.retrieve_scoped("猫咪吃什么", spawn_id=1, k=5))
    assert any("猫粮" in t for t in _texts(out))


def test_fts_only_without_provider(maker):
    from server.services import knowledge
    out = anyio.run(lambda: knowledge.retrieve_scoped("猫粮", spawn_id=1, k=5))
    assert len(out) == 2  # FTS 照常工作 = 今天的行为


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
