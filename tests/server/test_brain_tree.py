import pytest
import pytest_asyncio
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.api import brain as brain_api
from server.db.models import Base, Learning, UserFact
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


# --- brain-P1 Task 5: temporal field exposure on the tree leaves -----------------


@pytest.mark.asyncio
async def test_tree_profile_leaf_has_superseded_by_and_valid_from(maker):
    async with maker() as db:
        old = UserFact(content="旧偏好", category="cat", source="auto", confidence=0.6)
        new = UserFact(content="新偏好", category="cat", source="manual", confidence=0.9)
        db.add_all([old, new])
        await db.commit()
        await db.refresh(old)
        await db.refresh(new)
        old.superseded_by = new.id
        await db.commit()
        new_id, old_id = new.id, old.id

    tree = await brain_api.brain_tree()
    prof = next(b for b in tree["branches"] if b["kind"] == "profile")
    leaves = {leaf["ref"]: leaf for leaf in prof["children"]}
    assert leaves[f"fact:{old_id}"]["superseded_by"] == new_id
    assert "valid_from" in leaves[f"fact:{old_id}"]
    assert leaves[f"fact:{new_id}"]["superseded_by"] is None


@pytest.mark.asyncio
async def test_tree_learning_leaf_has_superseded_by_and_valid_from(maker):
    async with maker() as db:
        old = Learning(content="旧心得", source_kind="distill", source_ref={}, confidence=0.6)
        new = Learning(content="新心得更完整", source_kind="distill", source_ref={}, confidence=0.6)
        db.add_all([old, new])
        await db.commit()
        await db.refresh(old)
        await db.refresh(new)
        old.superseded_by = new.id
        await db.commit()
        new_id, old_id = new.id, old.id

    tree = await brain_api.brain_tree()
    learn = next(b for b in tree["branches"] if b["kind"] == "learning")
    leaves = {leaf["ref"]: leaf for leaf in learn["children"]}
    assert leaves[f"learning:{old_id}"]["superseded_by"] == new_id
    assert "valid_from" in leaves[f"learning:{old_id}"]
    assert leaves[f"learning:{new_id}"]["superseded_by"] is None
