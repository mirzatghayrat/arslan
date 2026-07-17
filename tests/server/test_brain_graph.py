import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.api import brain as brain_api
from server.db.models import Base, Learning, UserFact
from server.services import note_service


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'g.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
        await c.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text)")

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
    assert any(edge["type"] == "link" for edge in g["links"])       # note→note resolved
    assert any(str(edge["target"]).startswith("ghost:") for edge in g["links"])


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
    tag_edges = [edge for edge in g["links"]
                 if edge["type"] == "tag" and edge["target"] == "tag:finance"]
    assert len(tag_edges) == 2                                   # 两笔记各一条 → 同一标签
    assert any(edge["type"] == "hub" and edge["source"] == "self" and edge["target"] == "tag:finance"
               for edge in g["links"])                           # 你 → 标签簇


@pytest.mark.asyncio
async def test_graph_orphan_note_falls_back_to_self(maker):
    n = await note_service.create("孤儿笔记", "没有链接也没有标签", [])
    g = await brain_api.brain_graph()
    assert any(edge["type"] == "hub" and edge["source"] == "self" and edge["target"] == f"note:{n.id}"
               for edge in g["links"])


# --- brain-P1 Task 5: temporal field exposure (source/confidence/superseded_by) ---
# The fact/learning SELECTs widen (arity 4->7 for facts, 4->5 for learnings) to carry
# these fields; every tuple-unpack/index site downstream must track the new width or
# the endpoint crashes at runtime (brain.py's tag-linking loops unpack these rows by
# position). These tests exercise brain_graph() end-to-end with both tables populated,
# so a stale unpack raises ValueError and fails the test — not just "field missing".


@pytest.mark.asyncio
async def test_graph_fact_node_has_source_confidence_superseded_by(maker):
    async with db_session.AsyncSessionLocal() as db:
        old = UserFact(content="旧偏好", category="口味", source="auto", confidence=0.6)
        new = UserFact(content="新偏好", category="口味", source="manual", confidence=0.9)
        db.add_all([old, new])
        await db.commit()
        await db.refresh(old)
        await db.refresh(new)
        old.superseded_by = new.id
        await db.commit()
        new_id, old_id = new.id, old.id

    g = await brain_api.brain_graph()
    old_node = next(n for n in g["nodes"] if n["id"] == f"fact:{old_id}")
    new_node = next(n for n in g["nodes"] if n["id"] == f"fact:{new_id}")
    assert old_node["source"] == "auto"
    assert old_node["confidence"] == 0.6
    assert old_node["superseded_by"] == new_id
    assert new_node["source"] == "manual"
    assert new_node["confidence"] == 0.9
    assert new_node["superseded_by"] is None


@pytest.mark.asyncio
async def test_graph_learning_node_has_superseded_by(maker):
    async with db_session.AsyncSessionLocal() as db:
        old = Learning(content="旧心得", source_kind="distill", source_ref={}, confidence=0.6)
        new = Learning(content="新心得更完整", source_kind="distill", source_ref={}, confidence=0.6)
        db.add_all([old, new])
        await db.commit()
        await db.refresh(old)
        await db.refresh(new)
        old.superseded_by = new.id
        await db.commit()
        new_id, old_id = new.id, old.id

    g = await brain_api.brain_graph()
    old_node = next(n for n in g["nodes"] if n["id"] == f"learning:{old_id}")
    new_node = next(n for n in g["nodes"] if n["id"] == f"learning:{new_id}")
    assert old_node["superseded_by"] == new_id
    assert new_node["superseded_by"] is None


@pytest.mark.asyncio
async def test_graph_survives_mixed_facts_learnings_notes_no_arity_crash(maker):
    """Combined smoke: facts + learnings + tagged notes all present at once, so every
    widened-SELECT unpack site in brain_graph() (tag-linking loops included) runs."""
    async with db_session.AsyncSessionLocal() as db:
        db.add(UserFact(content="事实", category="cat", source="auto", confidence=0.5))
        db.add(Learning(content="心得", source_kind="distill", source_ref={"spawn_id": 1}, confidence=0.5))
        await db.commit()
    await note_service.create("笔记", "内容", ["cat"])

    g = await brain_api.brain_graph()
    assert g["nodes"]
    kinds = {n["kind"] for n in g["nodes"]}
    assert {"profile", "learning", "note"} <= kinds
