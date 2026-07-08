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
async def test_graph_empty(maker):
    g = await brain_api.brain_graph()
    assert g == {"nodes": [], "links": []}
