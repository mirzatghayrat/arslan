import anyio
import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.services import note_service


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'n.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
            await c.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text)")

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_crud_and_fts(maker):
    n = await note_service.create("OKX 模板", "参见 [[材料库]] 的 OKX", ["deck"])
    assert n.id and n.title == "OKX 模板"
    got = await note_service.get(n.id)
    assert got["title"] == "OKX 模板"
    # fts row exists → searchable via raw MATCH
    async with db_session.AsyncSessionLocal() as db:
        hit = (await db.execute(sa_text(
            "SELECT rowid FROM notes_fts WHERE text MATCH 'OKX'"))).first()
    assert hit is not None and hit[0] == n.id
    await note_service.update(n.id, title="OKX 模板 v2")
    assert (await note_service.get(n.id))["title"] == "OKX 模板 v2"
    await note_service.delete(n.id)
    assert await note_service.get(n.id) is None


def test_parse_links_and_backlinks():
    assert note_service.parse_links("看 [[A]] 和 [[B 笔记]] 还有 [[A]]") == ["A", "B 笔记"]
    assert note_service.parse_links("无链接") == []


@pytest.mark.asyncio
async def test_backlinks(maker):
    a = await note_service.create("目标", "", [])
    b = await note_service.create("来源", "引用 [[目标]]", [])
    bl = await note_service.backlinks("目标")
    assert any(x["id"] == b.id for x in bl)
