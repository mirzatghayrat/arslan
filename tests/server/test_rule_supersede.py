"""Rule-initiated supersede (brain-P1 Task 4): the fuzzy branch of save_facts /
learning_service._write upgrades from P0's "coexist + log" into three ways,
routed by fact_dedup.fuzzy_kind(new, old):

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
  - 中文沟通 / 中文进行沟通和输出 pair (the P0-b dedup-threshold anchor from
    test_fact_dedup_merge.py::test_save_facts_near_dup_coexists_not_merged):
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
from server.db.models import Base, Learning, MemoryProposal, UserFact
from server.services import fact_dedup
from server.services.memory_temporal import execute_supersede

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
    assert fact_dedup.fuzzy_kind("用户在北京工作", "用户来自甲城,是甲语母语者") is None


def test_fuzzy_kind_none_when_exact_norm_equal():
    # similar() is True (equal), but exact belongs to phase 1 and must never
    # reach the fuzzy branch's kind classification.
    assert fact_dedup.fuzzy_kind("同一句话啊", "同一句话啊") is None


# ---------------------------------------------------------------------------
# save_facts — extension: AUTO-supersede via the executor
# ---------------------------------------------------------------------------

async def test_save_facts_extension_auto_supersedes_with_concrete_id(maker):
    from server.orchestrator import memory

    a = await memory.save_facts([{"content": _SHORT}], provenance=_PROV)
    old_id = a[0].id
    b = await memory.save_facts([{"content": _LONG}], provenance=_PROV)
    new_id = b[0].id
    assert new_id != old_id

    async with maker() as s:
        old_row = await s.get(UserFact, old_id)
    # Concrete id, not just "is not None" -- this is what catches a missing
    # `await db.flush()` before execute_supersede (row.id would be None, and a
    # bare `is not None` assertion would pass on a wrong/no-op pointer).
    assert old_row.superseded_by == new_id

    active = await memory.list_facts()
    assert [f.id for f in active] == [new_id]

    text = await memory.facts_text()
    assert text == f"Known facts about the user:\n- {_LONG}"

    async with maker() as s:
        proposals = (await s.execute(select(MemoryProposal))).scalars().all()
    assert proposals == []  # extension auto-wins -- no soft-mark needed


# ---------------------------------------------------------------------------
# save_facts — shrink: reverse write order must NOT auto-supersede
# ---------------------------------------------------------------------------

async def test_save_facts_shrink_reverse_order_proposes_not_supersedes(maker):
    from server.orchestrator import memory

    a = await memory.save_facts([{"content": _LONG}], provenance=_PROV)
    old_id = a[0].id
    b = await memory.save_facts([{"content": _SHORT}], provenance=_PROV)
    new_id = b[0].id

    async with maker() as s:
        old_row = await s.get(UserFact, old_id)
        new_row = await s.get(UserFact, new_id)
    assert old_row.superseded_by is None
    assert new_row.superseded_by is None

    async with maker() as s:
        proposals = (await s.execute(select(MemoryProposal))).scalars().all()
    assert len(proposals) == 1
    p = proposals[0]
    assert p.table_name == "user_facts"
    assert p.new_id == new_id
    assert p.old_id == old_id
    assert p.reason.startswith("shrink:")
    assert p.status == "pending"
    assert p.provenance == _PROV


# ---------------------------------------------------------------------------
# save_facts — other: non-containment fuzzy hit proposes
# ---------------------------------------------------------------------------

async def test_save_facts_other_kind_coexists_and_proposes(maker):
    from server.orchestrator import memory

    a = await memory.save_facts([{"content": _OTHER_A}], provenance=_PROV)
    old_id = a[0].id
    b = await memory.save_facts([{"content": _OTHER_B}], provenance=_PROV)
    new_id = b[0].id

    async with maker() as s:
        old_row = await s.get(UserFact, old_id)
        new_row = await s.get(UserFact, new_id)
    assert old_row.superseded_by is None
    assert new_row.superseded_by is None

    async with maker() as s:
        rows = (await s.execute(select(UserFact))).scalars().all()
        proposals = (await s.execute(select(MemoryProposal))).scalars().all()
    assert len(rows) == 2  # both coexist

    assert len(proposals) == 1
    p = proposals[0]
    assert p.table_name == "user_facts"
    assert p.new_id == new_id
    assert p.old_id == old_id
    assert p.reason.startswith("other:")
    assert p.status == "pending"
    assert p.provenance == _PROV


# ---------------------------------------------------------------------------
# save_facts — below-threshold (0.800 < 0.85): pure coexist, ZERO proposal
# (P0 semantics anchor -- must not regress with Task 4's new proposal path)
# ---------------------------------------------------------------------------

async def test_save_facts_below_threshold_pair_pure_coexist_zero_proposal(maker):
    from server.orchestrator import memory

    assert fact_dedup.similar(_BELOW_A, _BELOW_B) is False  # sanity: never reaches fuzzy branch

    await memory.save_facts([{"content": _BELOW_A}], provenance=_PROV)
    await memory.save_facts([{"content": _BELOW_B}], provenance=_PROV)

    async with maker() as s:
        rows = (await s.execute(select(UserFact))).scalars().all()
        proposals = (await s.execute(select(MemoryProposal))).scalars().all()
    assert len(rows) == 2
    assert all(r.superseded_by is None for r in rows)
    assert proposals == []


# ---------------------------------------------------------------------------
# save_facts — fail-open hardening: a raise inside the fuzzy sub-block
# (flush / fuzzy_kind / execute_supersede / proposal add) must NOT take the
# whole batch hostage — the fact still persists as a plain coexisting row
# (no pointer, no proposal), a warning is logged, and created still returns it.
# ---------------------------------------------------------------------------

async def test_save_facts_supersede_failure_falls_back_to_pure_coexist(
        maker, monkeypatch, caplog):
    import logging as _logging

    from server.orchestrator import memory
    from server.services import memory_temporal

    async def _boom(*a, **k):
        raise RuntimeError("simulated executor failure")

    monkeypatch.setattr(memory_temporal, "execute_supersede", _boom)

    a = await memory.save_facts([{"content": _SHORT}], provenance=_PROV)
    old_id = a[0].id
    with caplog.at_level(_logging.WARNING, logger="server.orchestrator.memory"):
        b = await memory.save_facts([{"content": _LONG}], provenance=_PROV)
    assert len(b) == 1                        # created list still returns the new row
    new_id = b[0].id

    async with maker() as s:
        old_row = await s.get(UserFact, old_id)
        new_row = await s.get(UserFact, new_id)
    assert old_row.superseded_by is None       # no pointer written (fail-open)
    assert new_row.superseded_by is None       # both rows persisted and ACTIVE
    async with maker() as s:
        proposals = (await s.execute(select(MemoryProposal))).scalars().all()
    assert proposals == []                     # no proposal either — pure coexist

    assert "falling back to pure coexist" in caplog.text


# ---------------------------------------------------------------------------
# save_facts — writing content identical to a SUPERSEDED row: plain insert,
# zero reaction (Task 3's active-only property preserved through Task 4's
# fuzzy-branch upgrade)
# ---------------------------------------------------------------------------

async def test_save_facts_same_content_as_superseded_row_inserts_plain_no_proposal(maker):
    from server.orchestrator import memory

    async with maker() as s:
        old = UserFact(content="旧内容不再活跃了", source="auto")
        winner = UserFact(content="不相关的另一条事实", source="auto")
        s.add_all([old, winner])
        await s.commit()
        old_id, winner_id = old.id, winner.id
    await execute_supersede("user_facts", winner_id, old_id, provenance=_PROV)

    created = await memory.save_facts([{"content": "旧内容不再活跃了"}], provenance=_PROV)
    assert len(created) == 1
    assert created[0].id != old_id
    assert created[0].superseded_by is None

    async with maker() as s:
        proposals = (await s.execute(select(MemoryProposal))).scalars().all()
    assert proposals == []


# ---------------------------------------------------------------------------
# learning_service._write — same three-way mirror
# ---------------------------------------------------------------------------

async def test_learnings_extension_auto_supersedes_with_concrete_id(maker):
    from server.services.learning_service import _write

    n1 = await _write(_L_BASE, "l1", "distill", {"conversation_id": "c1"}, None)
    assert n1 == 1
    async with maker() as s:
        old_id = (await s.execute(
            select(Learning.id).where(Learning.content == _L_BASE))).scalar_one()

    n2 = await _write(_L_EXT, "l2", "distill", {"conversation_id": "c2"}, None)
    assert n2 == 1
    async with maker() as s:
        new_id = (await s.execute(
            select(Learning.id).where(Learning.content == _L_EXT))).scalar_one()
        old_row = await s.get(Learning, old_id)

    assert old_row.superseded_by == new_id  # concrete id -- catches missing flush

    async with maker() as s:
        proposals = (await s.execute(select(MemoryProposal))).scalars().all()
    assert proposals == []


async def test_learnings_other_kind_coexists_and_proposes(maker):
    from server.services.learning_service import _write

    n1 = await _write(_L_OTHER_A, "l1", "distill", {"conversation_id": "c1"}, None)
    assert n1 == 1
    async with maker() as s:
        old_id = (await s.execute(
            select(Learning.id).where(Learning.content == _L_OTHER_A))).scalar_one()

    n2 = await _write(_L_OTHER_B, "l2", "distill", {"conversation_id": "c2"}, None)
    assert n2 == 1
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
