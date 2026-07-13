import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.api import notes as notes_api
from server.db.models import Base


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'na.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
        await c.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text)")

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


class _Req:
    def __init__(self, body): self._b = body
    async def json(self): return self._b


@pytest.mark.asyncio
async def test_notes_crud_endpoints(maker):
    created = await notes_api.create_note(_Req({"title": "A", "content": "link [[B]]", "tags": ["x"]}))
    assert created["title"] == "A"
    got = await notes_api.get_note(created["id"])
    assert got["title"] == "A" and "backlinks" in got
    lst = await notes_api.list_notes()
    assert any(n["id"] == created["id"] for n in lst)
    assert (await notes_api.delete_note(created["id"]))["deleted"] is True
