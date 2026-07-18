"""brain-P2 Task 4: RememberExecutor's three-tier write authorization — the
HOST-actor path.

Covers:
  - Tier1 direct writes (reversible, immediate): host append fact/learning/note
    (with provenance); host supersede fact/learning (old row preserved); host
    mark_stale fact (provenance JSON flag) + undo (same action toggles it off).
  - Tier2 propose (never direct): host delete (any kind) always creates a
    delete_suspect MemoryProposal — the target row is untouched.
  - The action×kind capability matrix's negative space: supersede is only
    valid for fact/learning (note/preference → a clean "unsupported" error);
    mark_stale is only valid for fact (learning/note/preference → error).

Spawn-actor scope isolation (global-table downgrade to Tier2, own-well direct
writes, cross-well rejection, preference ownership, fail-closed identity) is
covered separately in tests/server/test_memory_scope_isolation.py — that file
also owns the "edit high-conf fact → edit_high_conf_suspect proposal" case,
since that proposal kind only fires on the spawn scope-downgrade path.
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Learning, MemoryProposal, Note, UserFact
from server.orchestrator.tool_caller import ToolCaller, reset_caller, set_caller
from server.registry.memory_executors import RememberExecutor


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tiers.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # FTS5 virtual tables aren't ORM models — note_service.create /
        # learning_service.append insert into them directly (same convention
        # as test_memory_tools_register.py / test_learning_service.py).
        await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text)")
        await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(text)")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest_asyncio.fixture(autouse=True)
async def _no_caller_leak():
    from server.orchestrator import tool_caller
    assert tool_caller.current_caller() is None
    yield
    assert tool_caller.current_caller() is None


_HOST = ToolCaller(actor="host", spawn_id=None, conversation_id="conv-tiers")


async def _remember(args: dict, caller: ToolCaller = _HOST) -> dict:
    token = set_caller(caller)
    try:
        return await RememberExecutor().execute(args)
    finally:
        reset_caller(token)


# ---------------------------------------------------------------------------
# Tier1 direct-write appends (host)
# ---------------------------------------------------------------------------

async def test_host_append_fact_direct_write_with_provenance(maker):
    out = await _remember({"kind": "fact", "action": "append", "content": "喜欢暗色主题"})
    assert out["ok"] is True and isinstance(out["id"], int)
    async with maker() as db:
        row = await db.get(UserFact, out["id"])
    assert row.content == "喜欢暗色主题"
    assert row.provenance["source_kind"] == "agentic"
    assert row.provenance["actor"] == "host"
    assert row.provenance["conversation_id"] == "conv-tiers"


async def test_host_append_learning_returns_real_id_and_writes(maker):
    out = await _remember({"kind": "learning", "action": "append",
                            "content": "先写测试再实现,红绿分明"})
    assert out["ok"] is True
    assert isinstance(out["id"], int) and out["id"] > 0
    async with maker() as db:
        row = await db.get(Learning, out["id"])
    assert row is not None
    assert row.content == "先写测试再实现,红绿分明"
    assert row.source_kind == "agentic"
    assert row.source_ref["actor"] == "host"           # dual-track: learning rides source_ref


async def test_host_append_note_direct_write(maker):
    out = await _remember({"kind": "note", "action": "append",
                            "content": "记得写完成报告"})
    assert out["ok"] is True and isinstance(out["id"], int)
    async with maker() as db:
        row = await db.get(Note, out["id"])
    assert "记得写完成报告" in row.content


# ---------------------------------------------------------------------------
# Tier1 supersede (host) — old row preserved, never deleted
# ---------------------------------------------------------------------------

async def test_host_supersede_fact_preserves_old_row(maker):
    async with maker() as db:
        old = UserFact(content="旧偏好:亮色主题", source="manual",
                       provenance={"source_kind": "manual"})
        db.add(old)
        await db.commit()
        old_id = old.id

    out = await _remember({"kind": "fact", "action": "supersede", "target_id": old_id,
                            "content": "新偏好:暗色主题"})
    assert out["ok"] is True
    new_id = out["id"]
    assert new_id != old_id

    async with maker() as db:
        old_row = await db.get(UserFact, old_id)
        new_row = await db.get(UserFact, new_id)
    assert old_row is not None                          # preserved, not deleted
    assert old_row.superseded_by == new_id
    assert new_row.content == "新偏好:暗色主题"


async def test_host_supersede_learning_preserves_old_row(maker):
    async with maker() as db:
        old = Learning(content="旧心得:先问再做", source_kind="manual", source_ref={"x": 1})
        db.add(old)
        await db.commit()
        old_id = old.id

    out = await _remember({"kind": "learning", "action": "supersede", "target_id": old_id,
                            "content": "新心得:先问清楚范围再动手"})
    assert out["ok"] is True
    new_id = out["id"]

    async with maker() as db:
        old_row = await db.get(Learning, old_id)
        new_row = await db.get(Learning, new_id)
    assert old_row is not None
    assert old_row.superseded_by == new_id
    assert new_row.content == "新心得:先问清楚范围再动手"


# ---------------------------------------------------------------------------
# Tier1 mark_stale (host, fact only) — same action undoes it (toggle)
# ---------------------------------------------------------------------------

async def test_host_mark_stale_fact_then_undo(maker):
    async with maker() as db:
        row = UserFact(content="临时地址", source="manual", provenance={"source_kind": "manual"})
        db.add(row)
        await db.commit()
        fid = row.id

    out = await _remember({"kind": "fact", "action": "mark_stale", "target_id": fid, "content": ""})
    assert out["ok"] is True
    async with maker() as db:
        row = await db.get(UserFact, fid)
    assert row.provenance.get("stale") is True
    assert "marked_at" in row.provenance

    out2 = await _remember({"kind": "fact", "action": "mark_stale", "target_id": fid, "content": ""})
    assert out2["ok"] is True
    async with maker() as db:
        row = await db.get(UserFact, fid)
    assert row.provenance.get("stale") is not True       # undo cleared the mark
    assert "marked_at" not in row.provenance


# ---------------------------------------------------------------------------
# Tier2: delete always proposes, never direct
# ---------------------------------------------------------------------------

async def test_host_delete_fact_creates_proposal_not_a_deletion(maker):
    async with maker() as db:
        row = UserFact(content="不要删我", source="manual", provenance={"source_kind": "manual"})
        db.add(row)
        await db.commit()
        fid = row.id

    out = await _remember({"kind": "fact", "action": "delete", "target_id": fid, "content": ""})
    assert out["ok"] is True and out["proposed"] is True
    assert isinstance(out["proposal_id"], int)

    async with maker() as db:
        proposals = (await db.execute(select(MemoryProposal))).scalars().all()
        still_there = await db.get(UserFact, fid)
    assert len(proposals) == 1
    p = proposals[0]
    assert p.kind == "delete_suspect"
    assert p.table_name == "user_facts"
    assert p.old_id == fid
    assert p.status == "pending"
    assert still_there is not None                        # not actually deleted


# ---------------------------------------------------------------------------
# Negative matrix: supersede only valid for fact/learning; mark_stale only fact
# ---------------------------------------------------------------------------

async def test_host_supersede_note_is_unsupported(maker):
    out = await _remember({"kind": "note", "action": "supersede", "target_id": 1, "content": "x"})
    assert out["ok"] is False
    assert "unsupported" in out["error"].lower()


async def test_host_supersede_preference_is_unsupported(maker):
    out = await _remember({"kind": "preference", "action": "supersede", "target_id": 1, "content": "x"})
    assert out["ok"] is False
    assert "unsupported" in out["error"].lower()


async def test_host_mark_stale_learning_is_unsupported(maker):
    out = await _remember({"kind": "learning", "action": "mark_stale", "target_id": 1, "content": ""})
    assert out["ok"] is False
    assert "unsupported" in out["error"].lower()


async def test_host_mark_stale_note_is_unsupported(maker):
    out = await _remember({"kind": "note", "action": "mark_stale", "target_id": 1, "content": ""})
    assert out["ok"] is False
    assert "unsupported" in out["error"].lower()


async def test_host_mark_stale_preference_is_unsupported(maker):
    out = await _remember({"kind": "preference", "action": "mark_stale", "target_id": 1, "content": ""})
    assert out["ok"] is False
    assert "unsupported" in out["error"].lower()
