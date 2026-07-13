import pytest
import pytest_asyncio
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.api import brain as brain_api
from server.db.models import Base
from server.services import note_service


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'t.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
        await c.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text)")

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_tree_note_leaf_has_tags(maker):
    await note_service.create("带标签笔记", "内容", ["finance", "ops"])
    tree = await brain_api.brain_tree()
    note_branch = next(b for b in tree["branches"] if b["kind"] == "note")
    leaf = note_branch["children"][0]
    assert leaf["tags"] == ["finance", "ops"]


@pytest.mark.asyncio
async def test_tree_profile_leaf_has_category(maker):
    async with maker() as db:
        await db.execute(sa_text(
            "INSERT INTO user_facts (content, label, category, source, confidence) "
            "VALUES ('在北京工作', '北京', '身份背景', 'auto', 0.9)"))
        await db.commit()
    tree = await brain_api.brain_tree()
    prof = next(b for b in tree["branches"] if b["kind"] == "profile")
    assert prof["children"][0]["category"] == "身份背景"
