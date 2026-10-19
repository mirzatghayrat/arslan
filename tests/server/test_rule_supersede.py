"""Rule-initiated supersede (brain-P1 Task 4): the fuzzy branch of
learning_service._write upgrades from P0's "coexist + log" into three ways,
routed by fact_dedup.fuzzy_kind(new, old). (memory.save_facts had the same
branch on v1 user_facts; its tests went with that path in C2a.)

  extension = old ⊂ new (both norm-strings >= _MIN_CONTAINMENT_LEN) → AUTO-supersede
              via memory_temporal.execute_supersede (executor guards, in-transaction).
  shrink    = new ⊂ old (same length gate)                          → coexist + MemoryProposal.
  other     = similar()-true, neither containment direction          → coexist + MemoryProposal.
  None      = not similar (exact is phase 1; <0.85 never reaches here) → pure coexist, no reaction.

Direction lock (load-bearing, do not invert): "new EXTENDS old" means old is the
shorter/contained string — the new, more informative write auto-wins. A downgrade
(new is the SHRUNK version) must never auto-win, hence "shrink" always proposes.

Anchor ratios (verified via difflib.SequenceMatcher on norm()'d strings, all CJK
so norm() is whitespace/case-only and doesn't touch containment):
  - 朝阳区 / 朝阳区望京 pair: ratio=0.9,    containment=True  (extension/shrink anchors)
  - 公园跑步 / 公园散步 pair: ratio=0.9167, containment=False (other anchor)
  - 中文沟通 / 中文进行沟通和输出 pair (the P0-b dedup-threshold anchor, once
    pinned by save_facts' near-dup test, removed in C2a):
    ratio=0.800 < 0.85 → similar() is False → never reaches the fuzzy branch at
    all → zero MemoryProposal rows (P0 semantics must not regress).
  - 用户需要广告科技助手 / ...(AdTech)... pair: ratio=0.606 (even further below
    threshold; the "广告科技" pair from the P0-b test comment for reference).
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Learning, MemoryProposal
from server.services import fact_dedup

_PROV = {"source_kind": "test"}

# ---------------------------------------------------------------------------
# Anchor pairs (verified difflib ratios in the module docstring above)
# ---------------------------------------------------------------------------
_SHORT = "我住在北京市朝阳区"                 # 9 chars
_LONG = "我住在北京市朝阳区望京"               # 11 chars, _SHORT is a prefix of it
_OTHER_A = "用户喜欢在周末去公园跑步"          # 12 chars
_OTHER_B = "用户喜欢在周末去公园散步"          # 12 chars, same len, no containment, ratio 0.9167
_BELOW_A = "用户偏好使用中文沟通"              # the P0-b 0.800 anchor pair
_BELOW_B = "用户偏好使用中文进行沟通和输出"

_L_BASE = "用户喜欢先给结论再讲细节"           # 12 chars
_L_EXT = _L_BASE + "并配图表"                 # 16 chars, _L_BASE is a prefix
_L_OTHER_A = "总结要先给结论后细节"            # 10 chars
_L_OTHER_B = "总结要先给结果后细节"            # 10 chars, no containment, ratio 0.9


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'rule_supersede.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(text)")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


# ---------------------------------------------------------------------------
# fact_dedup.fuzzy_kind — pure function, direction classification
# ---------------------------------------------------------------------------

def test_fuzzy_kind_extension_when_old_is_prefix_of_new():
    assert fact_dedup.fuzzy_kind(_LONG, _SHORT) == "extension"


def test_fuzzy_kind_shrink_when_new_is_prefix_of_old():
    # reverse direction of the same pair: new is the SHRUNK one -> must not be
    # classified as extension (direction lock)
    assert fact_dedup.fuzzy_kind(_SHORT, _LONG) == "shrink"


def test_fuzzy_kind_other_for_non_containment_similar_pair():
    assert fact_dedup.fuzzy_kind(_OTHER_A, _OTHER_B) == "other"


def test_fuzzy_kind_none_when_not_similar():
    assert fact_dedup.fuzzy_kind(_BELOW_A, _BELOW_B) is None
    assert fact_dedup.fuzzy_kind("用户在乙城工作", "用户来自甲城,母语是甲语") is None


def test_fuzzy_kind_none_when_exact_norm_equal():
    # similar() is True (equal), but exact belongs to phase 1 and must never
    # reach the fuzzy branch's kind classification.
    assert fact_dedup.fuzzy_kind("同一句话啊", "同一句话啊") is None


# ---------------------------------------------------------------------------
# learning_service._write — same three-way mirror
# ---------------------------------------------------------------------------

async def test_learnings_extension_auto_supersedes_with_concrete_id(maker):
    from server.services.learning_service import _write

    n1 = await _write(_L_BASE, "l1", "distill", {"conversation_id": "c1"}, None)
    assert n1 > 0                                       # P2: real id, not a 1/0 flag
    async with maker() as s:
        old_id = (await s.execute(
            select(Learning.id).where(Learning.content == _L_BASE))).scalar_one()
    assert n1 == old_id                                 # P2 BLOCKER fix: _write returns the real row id

    n2 = await _write(_L_EXT, "l2", "distill", {"conversation_id": "c2"}, None)
    assert n2 > 0
    async with maker() as s:
        new_id = (await s.execute(
            select(Learning.id).where(Learning.content == _L_EXT))).scalar_one()
        old_row = await s.get(Learning, old_id)
    assert n2 == new_id

    assert old_row.superseded_by == new_id  # concrete id -- catches missing flush

    async with maker() as s:
        proposals = (await s.execute(select(MemoryProposal))).scalars().all()
    assert proposals == []


async def test_learnings_other_kind_coexists_and_proposes(maker):
    from server.services.learning_service import _write

    n1 = await _write(_L_OTHER_A, "l1", "distill", {"conversation_id": "c1"}, None)
    assert n1 > 0                                       # P2: real id, not a 1/0 flag
    async with maker() as s:
        old_id = (await s.execute(
            select(Learning.id).where(Learning.content == _L_OTHER_A))).scalar_one()
    assert n1 == old_id

    n2 = await _write(_L_OTHER_B, "l2", "distill", {"conversation_id": "c2"}, None)
    assert n2 > 0
    async with maker() as s:
        new_id = (await s.execute(
            select(Learning.id).where(Learning.content == _L_OTHER_B))).scalar_one()
        old_row = await s.get(Learning, old_id)
    assert old_row.superseded_by is None  # no auto-supersede for "other"

    async with maker() as s:
        proposals = (await s.execute(select(MemoryProposal))).scalars().all()
    assert len(proposals) == 1
    p = proposals[0]
    assert p.table_name == "learnings"
    assert p.new_id == new_id
    assert p.old_id == old_id
    assert p.reason.startswith("other:")
    assert p.status == "pending"
    assert p.provenance == {"source_kind": "distill", "conversation_id": "c2"}


# ---------------------------------------------------------------------------
# brain-P2 Task 4 cross-well fix (whole-branch review): _write's dedup/fuzzy
# candidate set is scoped to the SAME WELL (spawn_id IS :sid, NULL-safe). The
# implicit "extension" auto-supersede must NEVER deactivate a learning the
# writer doesn't own — otherwise a spawn appending extending content could
# silently supersede another spawn's (or a global) learning with no proposal
# and no human gate, bypassing the explicit supersede path's scope check.
# ---------------------------------------------------------------------------

async def test_extension_does_not_cross_well_from_spawn_to_other_spawn(maker):
    from server.services.learning_service import _write

    # spawn B owns the base learning.
    await _write(_L_BASE, "l1", "agentic", {"actor": "spawn:2"}, 2)
    async with maker() as s:
        b_id = (await s.execute(
            select(Learning.id).where(Learning.content == _L_BASE))).scalar_one()

    # spawn A appends content that fuzzy-EXTENDS B's learning. Same content,
    # different well -> must NOT auto-supersede B's row; a NEW row is written
    # in A's own well.
    a_new = await _write(_L_EXT, "l2", "agentic", {"actor": "spawn:1"}, 1)
    assert a_new > 0
    async with maker() as s:
        b_row = await s.get(Learning, b_id)
        a_row = await s.get(Learning, a_new)
        proposals = (await s.execute(select(MemoryProposal))).scalars().all()
    assert b_row.superseded_by is None       # other spawn's row stays ACTIVE
    assert a_row.spawn_id == 1                # new row is in A's own well
    assert a_row.superseded_by is None
    assert proposals == []                    # no cross-well proposal either


async def test_extension_does_not_cross_well_from_spawn_to_global(maker):
    from server.services.learning_service import _write

    # A GLOBAL (host, spawn_id=None) learning.
    await _write(_L_BASE, "l1", "agentic", {"actor": "host"}, None)
    async with maker() as s:
        g_id = (await s.execute(
            select(Learning.id).where(Learning.content == _L_BASE))).scalar_one()

    # A spawn appends extending content -> must NOT touch the global row.
    a_new = await _write(_L_EXT, "l2", "agentic", {"actor": "spawn:1"}, 1)
    assert a_new > 0
    async with maker() as s:
        g_row = await s.get(Learning, g_id)
    assert g_row.superseded_by is None       # global row stays ACTIVE


async def test_same_content_two_spawns_coexist_no_cross_well_dedup(maker):
    from server.services.learning_service import _write

    n1 = await _write(_L_BASE, "l1", "agentic", {"actor": "spawn:1"}, 1)
    n2 = await _write(_L_BASE, "l2", "agentic", {"actor": "spawn:2"}, 2)
    assert n1 > 0 and n2 > 0 and n1 != n2    # exact-dup skip is same-well only
    async with maker() as s:
        rows = (await s.execute(
            select(Learning).where(Learning.content == _L_BASE))).scalars().all()
    assert len(rows) == 2
    assert {r.spawn_id for r in rows} == {1, 2}
    assert all(r.superseded_by is None for r in rows)


async def test_extension_still_auto_supersedes_within_own_well(maker):
    """The scoping fix must NOT break same-well auto-supersede: a spawn
    extending its OWN prior learning still auto-wins (own well unaffected)."""
    from server.services.learning_service import _write

    await _write(_L_BASE, "l1", "agentic", {"actor": "spawn:1"}, 1)
    async with maker() as s:
        old_id = (await s.execute(
            select(Learning.id).where(Learning.content == _L_BASE))).scalar_one()

    new_id = await _write(_L_EXT, "l2", "agentic", {"actor": "spawn:1"}, 1)
    assert new_id > 0
    async with maker() as s:
        old_row = await s.get(Learning, old_id)
    assert old_row.superseded_by == new_id   # own-well extension still auto-supersedes
