import dataclasses
import datetime as dt

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.config as config
import server.db.session as db_session
from server.api import brain
from server.db.models import Base
from server.services import brain_usage


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'brain.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def _leaves(node):
    kids = node.get("children") or []
    if not kids:
        yield node
    for k in kids:
        yield from _leaves(k)


@pytest.mark.asyncio
async def test_brain_tree_three_branches_with_fields(maker):
    now = dt.datetime.utcnow()
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(sa_text(
            "INSERT INTO user_facts (content, label, category, source, confidence) "
            "VALUES ('用户在Acme当AE', 'Acme AE', '身份背景', 'auto', 0.9)"))
        await db.execute(sa_text("INSERT INTO collections (id, name, created_at) VALUES (1,'c',:ts)"),
                         {"ts": now})
        await db.execute(sa_text(
            "INSERT INTO knowledge_chunks (collection_id, source, chunk_index, text, created_at) "
            "VALUES (1, 'okx.pdf', 0, '正文', :ts)"), {"ts": now})
        await db.execute(sa_text(
            "INSERT INTO learnings (content, label, source_kind, source_ref, confidence, created_at) "
            "VALUES ('做deck先套暗色模板', 'deck心得', 'distill', '{\"conversation_id\":\"c\"}', 0.6, :ts)"),
            {"ts": now})
        await db.execute(sa_text(
            "INSERT INTO notes (title, content, tags, created_at, updated_at) "
            "VALUES ('OKX 模板', '参见材料库', '[]', :ts, :ts)"), {"ts": now})
        await db.commit()
    await brain_usage.record("material", "material:coll:1:okx.pdf", used_ref="conv-x")

    body = await brain.brain_tree()
    kinds = {b["kind"] for b in body["branches"]}
    assert kinds == {"material", "learning", "profile", "note"}
    for b in body["branches"]:
        for leaf in _leaves(b):
            assert "usage_count" in leaf and "provenance" in leaf

    mat = next(b for b in body["branches"] if b["kind"] == "material")
    assert mat["children"][0]["usage_count"] == 1
    assert mat["children"][0]["value"] == 2  # 1 + usage_count, never 0


@pytest.mark.asyncio
async def test_brain_entry_material_excerpt(maker):
    now = dt.datetime.utcnow()
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(sa_text("INSERT INTO collections (id, name, created_at) VALUES (2,'c2',:ts)"),
                         {"ts": now})
        await db.execute(sa_text(
            "INSERT INTO knowledge_chunks (collection_id, source, chunk_index, text, created_at) "
            "VALUES (2, 'doc.pdf', 0, 'CHUNK ONE', :ts)"), {"ts": now})
        await db.commit()

    entry = await brain.brain_entry("material", "material:coll:2:doc.pdf")
    assert "CHUNK ONE" in entry["excerpt"]
    assert entry["provenance"] == "投喂"


# --- brain-P1 Task 5: temporal fields on /brain/entry (fact/learning) ------------
# NOTE: this endpoint already had a "provenance" key before P1 — a human-readable
# composite display string (category/source or source_kind/source_ref), asserted
# above (test_brain_entry_material_excerpt) and consumed by the shipped frontend
# (BrainEntryDetail.tsx renders `entry.provenance` as text; BrainNav.tsx groups by
# it). The real temporal audit payload is therefore exposed under a NON-colliding
# key, "provenance_record", so it doesn't silently turn that existing string field
# into an object and break the live frontend read. See task-5-report.md for the
# full rationale.


@pytest.mark.asyncio
async def test_brain_entry_fact_has_temporal_fields(maker):
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(sa_text(
            "INSERT INTO user_facts (content, label, category, source, confidence, provenance) "
            "VALUES ('在北京工作', '北京', '身份背景', 'auto', 0.9, '{\"source_kind\": \"test\"}')"))
        await db.commit()
        fid = (await db.execute(sa_text("SELECT id FROM user_facts"))).scalar()

    entry = await brain.brain_entry("profile", f"fact:{fid}")
    assert entry["provenance"] == "身份背景 · auto"          # unchanged display string
    assert "valid_from" in entry
    assert entry["superseded_by"] is None
    assert entry["provenance_record"] == {"source_kind": "test"}


@pytest.mark.asyncio
async def test_brain_entry_learning_has_temporal_fields(maker):
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(sa_text(
            "INSERT INTO learnings (content, label, source_kind, source_ref, confidence) "
            "VALUES ('心得', '标签', 'distill', '{\"conversation_id\": \"c\"}', 0.6)"))
        await db.commit()
        lid = (await db.execute(sa_text("SELECT id FROM learnings"))).scalar()

    entry = await brain.brain_entry("learning", f"learning:{lid}")
    assert "valid_from" in entry
    assert "superseded_by" in entry
    assert entry["provenance_record"] == {
        "source_kind": "distill", "source_ref": {"conversation_id": "c"}}


# --- auth gating (brain reads user profile/facts/notes structure) ----------
# require_auth reads config.settings at call time, so swapping the frozen
# Settings for one with a token set (auto-restored by monkeypatch) exercises
# the "token configured" path without importlib.reload contaminating globals.


@pytest.mark.asyncio
async def test_brain_requires_auth_when_token_set(maker, monkeypatch):
    monkeypatch.setattr(config, "settings",
                        dataclasses.replace(config.settings, api_token="secret-tok"))
    from server.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/brain/tree")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_brain_open_when_token_unset(maker):
    # Default test env leaves ARSLAN_API_TOKEN unset -> require_auth is a no-op.
    from server.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/brain/tree")
    assert r.status_code == 200
