"""Active-only retrieval (superseded_by IS NULL) on the v1 tables (brain-P1 Task 3, BLOCKER #2):
learning_service._write's scan, _learnings_route filtering, POST /facts/dedup's temporal safety
guard, and the #12 hermetic regression.

C2a removed the tests of memory.py's v1 fact paths (list_facts / facts_text active-only, the
save_facts and add_manual_fact scanners, the facts API's _to_out over them): every launch runs
memory v2, which has no superseded_by. The rest test v1 code that C2a-2 deletes.
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Learning, UserFact
from server.services.memory_temporal import execute_supersede

_PROV = {"source_kind": "test"}


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'active.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(text)")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


# ---------------------------------------------------------------------------
# Scanner #5 (BLOCKER #2): a write matching a SUPERSEDED row's exact content must
# insert a fresh ACTIVE row — never merge/skip/collide with the dead row.
# Scanners #1-#4 were memory.py's v1 fact writes (gone in C2a); #6, upflow's own
# local scan, is gone entirely — see BLOCKER #1 / distill_service.
# ---------------------------------------------------------------------------

async def test_learnings_same_content_as_superseded_inserts_new_active_row(maker):
    """Scanner #5: learning_service._write's existing-scan must exclude
    superseded rows (and fetches (id, content), not just content — Task 4's
    rule-supersede pointer write needs the id)."""
    from server.services.learning_service import _write

    async with maker() as s:
        old = Learning(content="总结要先给结论", source_kind="distill", source_ref={"x": 1})
        winner = Learning(content="unrelated learning", source_kind="distill", source_ref={"x": 2})
        s.add_all([old, winner])
        await s.commit()
        old_id, new_id = old.id, winner.id
    await execute_supersede("learnings", new_id, old_id, provenance=_PROV)

    n = await _write("总结要先给结论", "l1", "session", {}, None)
    assert n > 0                                       # inserted, not skipped as dup (P2: n is now a real id)
    async with maker() as s:
        rows = (await s.execute(
            select(Learning).where(Learning.content == "总结要先给结论"))).scalars().all()
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# _learnings_route: excludes superseded 心得 from retrieval
# ---------------------------------------------------------------------------

async def test_learnings_route_excludes_superseded(maker):
    from server.services import knowledge

    async with maker() as s:
        old = Learning(content="做 deck 要用暗色磨砂玻璃模板", source_kind="distill",
                       source_ref={"x": 1})
        winner = Learning(content="unrelated learning content here", source_kind="distill",
                          source_ref={"x": 2})
        s.add_all([old, winner])
        await s.commit()
        old_id, new_id = old.id, winner.id
        await s.execute(sa_text(
            "INSERT INTO learnings_fts (rowid, text) VALUES (:r, :t)"),
            {"r": old_id, "t": old.content})
        await s.commit()
    await execute_supersede("learnings", new_id, old_id, provenance=_PROV)

    async with maker() as db:
        hits = await knowledge._learnings_route(db, "暗色磨砂玻璃模板", None)
    assert old_id not in hits


# ---------------------------------------------------------------------------
# POST /facts/dedup temporal safety: active-only scan + never delete a row
# that is itself a supersede-pointer TARGET (would dangle the pointer)
# ---------------------------------------------------------------------------

async def test_dedup_facts_preserves_supersede_target_but_still_dedups_others(maker):
    from server.services import fact_dedup
    async with maker() as s:
        a = UserFact(content="喜欢猫", source="auto")  # id1, kept (first seen)
        b = UserFact(content="喜欢猫", source="auto")  # id2, plain dup -> deleted
        c = UserFact(content="喜欢猫", source="auto")  # id3, dup BUT a supersede target
        s.add_all([a, b, c])
        await s.commit()
        a_id, b_id, c_id = a.id, b.id, c.id
    async with maker() as s:
        d = UserFact(content="老版本(已取代)", source="auto", superseded_by=c_id)
        s.add(d)
        await s.commit()

    deleted = await fact_dedup.dedup_facts()
    assert deleted == 1

    async with maker() as s:
        remaining_ids = {r.id for r in (await s.execute(select(UserFact))).scalars().all()}
    assert a_id in remaining_ids
    assert b_id not in remaining_ids
    assert c_id in remaining_ids  # target survives even though it norm-duplicates a


async def test_dedup_merge_facts_preserves_supersede_target(maker):
    from server.services import fact_dedup
    async with maker() as s:
        a = UserFact(content="用户母语是甲语,来自甲城", source="auto")        # id1 kept
        c = UserFact(content="用户母语是甲语,来自甲城地区", source="auto")  # id2 fuzzy-dup, is a target
        s.add_all([a, c])
        await s.commit()
        a_id, c_id = a.id, c.id
    async with maker() as s:
        d = UserFact(content="老版本(已取代)", source="auto", superseded_by=c_id)
        s.add(d)
        await s.commit()

    deleted = await fact_dedup.dedup_merge_facts()
    assert deleted == 0  # c is a supersede target -> not collapsed away

    async with maker() as s:
        remaining_ids = {r.id for r in (await s.execute(select(UserFact))).scalars().all()}
    assert a_id in remaining_ids
    assert c_id in remaining_ids


# ---------------------------------------------------------------------------
# #12 hermetic regression: record_usage=False still writes zero brain_usage
# (pre-existing invariant). Its facts_text half went with memory.py's v1 path (C2a).
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def memdb(tmp_path, monkeypatch):
    from server.db.migrations.versions._0009_knowledge import upgrade_sync as kb_upgrade
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'hermetic.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(kb_upgrade)
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(text)")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


async def test_hermetic_record_usage_false_writes_no_usage(memdb):
    from server.db.models import BrainUsage, Spawn
    from server.services import ingest, knowledge

    async with memdb() as s:
        spawn = Spawn(name="H", domain_category="x", system_prompt="p")
        s.add(spawn)
        await s.commit()
        await s.refresh(spawn)
        sid = spawn.id
    await ingest.ingest_text(sid, "doc", "Refund policy is 30 days for all orders.")

    await knowledge.retrieve_scoped("refund", spawn_id=sid, record_usage=False)

    async with memdb() as s:
        rows = (await s.execute(select(BrainUsage))).scalars().all()
    assert rows == []  # unchanged hermetic guarantee: no usage rows on record_usage=False
