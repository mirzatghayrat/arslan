import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.api import brain as brain_api
from server.db.models import Base
from server.services import note_service


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'g.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
            await c.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text)")

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_graph_note_link_and_ghost(maker):
    await note_service.create("目标笔记", "内容", [])
    await note_service.create("来源笔记", "见 [[目标笔记]] 和 [[不存在的]]", [])
    g = await brain_api.brain_graph()
    kinds = {n["kind"] for n in g["nodes"]}
    assert "note" in kinds
    assert any(n["kind"] == "ghost" for n in g["nodes"])            # 不存在的 → ghost
    assert any(l["type"] == "link" for l in g["links"])             # note→note resolved
    assert any(str(l["target"]).startswith("ghost:") for l in g["links"])


@pytest.mark.asyncio
async def test_graph_has_self_hub_when_empty(maker):
    g = await brain_api.brain_graph()
    assert g["links"] == []
    assert len(g["nodes"]) == 1
    assert g["nodes"][0]["id"] == "self"
    assert g["nodes"][0]["kind"] == "self"


@pytest.mark.asyncio
async def test_graph_tag_nodes_link_shared(maker):
    await note_service.create("报销单", "内容", ["finance"])
    await note_service.create("预算表", "内容", ["finance"])
    g = await brain_api.brain_graph()
    assert any(n["id"] == "tag:finance" and n["kind"] == "tag" for n in g["nodes"])
    tag_edges = [l for l in g["links"] if l["type"] == "tag" and l["target"] == "tag:finance"]
    assert len(tag_edges) == 2                                   # 两笔记各一条 → 同一标签
    assert any(l["type"] == "hub" and l["source"] == "self" and l["target"] == "tag:finance"
               for l in g["links"])                              # 你 → 标签簇


@pytest.mark.asyncio
async def test_graph_orphan_note_falls_back_to_self(maker):
    n = await note_service.create("孤儿笔记", "没有链接也没有标签", [])
    g = await brain_api.brain_graph()
    assert any(l["type"] == "hub" and l["source"] == "self" and l["target"] == f"note:{n.id}"
               for l in g["links"])
