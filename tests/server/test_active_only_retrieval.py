"""Active-only retrieval (superseded_by IS NULL) + the six dedup scanners that
must never collide a new write with a dead (superseded) row (brain-P1 Task 3,
BLOCKER #2). Also covers list_facts(include_superseded=), _to_out field
population (BLOCKER: else valid_from/superseded_by/provenance are null forever),
_learnings_route filtering, POST /facts/dedup's temporal safety guard, and the
#12 hermetic regression.
"""
from __future__ import annotations

import importlib

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
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


async def _seed_superseded_fact(maker, content: str) -> tuple[int, int]:
    """Insert an old (soon-superseded) UserFact + a throwaway winner, execute the
    supersede pointer, return (old_id, new_id)."""
    async with maker() as s:
        old = UserFact(content=content, source="auto")
        winner = UserFact(content="totally unrelated other fact", source="auto")
        s.add_all([old, winner])
        await s.commit()
        old_id, new_id = old.id, winner.id
    await execute_supersede("user_facts", new_id, old_id, provenance=_PROV)
    return old_id, new_id


# ---------------------------------------------------------------------------
# list_facts / facts_text default to active-only (P0 throat — all 5 injection
# sites inherit this for free via facts_text -> list_facts)
# ---------------------------------------------------------------------------

async def test_list_facts_excludes_superseded_by_default(maker):
    from server.orchestrator import memory
    old_id, new_id = await _seed_superseded_fact(maker, "旧偏好")
    facts = await memory.list_facts()
    ids = [f.id for f in facts]
    assert old_id not in ids
    assert new_id in ids


async def test_list_facts_include_superseded_true_includes_it(maker):
    from server.orchestrator import memory
    old_id, _new_id = await _seed_superseded_fact(maker, "旧偏好2")
    facts = await memory.list_facts(include_superseded=True)
    assert old_id in [f.id for f in facts]


async def test_facts_text_excludes_superseded(maker):
    """P0 throat anchor: facts_text() -> list_facts() active-only, so the ONE
    render function feeding all 5 injection sites drops dead facts for free."""
    from server.orchestrator import memory
    await _seed_superseded_fact(maker, "旧偏好三三三三")
    text = await memory.facts_text()
    assert "旧偏好三三三三" not in text
    assert "totally unrelated other fact" in text


# ---------------------------------------------------------------------------
# Six-scanner active-only coverage (BLOCKER #2): a write matching a SUPERSEDED
# row's exact content must insert a fresh ACTIVE row — never merge/skip/collide
# with the dead row. Three production paths, one test each (scanners #1+#2 via
# save_facts, #3+#4 via add_manual_fact, #5 via learning_service._write; #6
# upflow's own local scan is gone entirely — see BLOCKER #1 / distill_service).
# ---------------------------------------------------------------------------

async def test_save_facts_same_content_as_superseded_inserts_new_active_row(maker):
    """Scanners #1 exact_norm_dup + #2 find_near_dup: save_facts's write-time
    two-phase dedup must not treat a superseded row as a duplicate target."""
    from server.orchestrator import memory
    old_id, _new_id = await _seed_superseded_fact(maker, "喜欢猫")
    created = await memory.save_facts([{"content": "喜欢猫"}], provenance=_PROV)
    assert len(created) == 1                        # inserted, not merged/skipped
    assert created[0].id != old_id
    assert created[0].superseded_by is None          # fresh row is active
    async with maker() as s:
        rows = (await s.execute(
            select(UserFact).where(UserFact.content == "喜欢猫"))).scalars().all()
    assert len(rows) == 2                             # dead old row + new active row coexist


async def test_add_manual_fact_same_content_as_superseded_inserts_new_active_row(maker):
    """Scanners #3 fact_dedup.existing_norms + #4 add_manual_fact's inline
    rescan (memory.py ~273-276)."""
    from server.orchestrator import memory
    old_id, _new_id = await _seed_superseded_fact(maker, "建 GitHub 分身")
    row = await memory.add_manual_fact("建 GitHub 分身")
    assert row.id != old_id
    assert row.superseded_by is None
    async with maker() as s:
        rows = (await s.execute(
            select(UserFact).where(UserFact.content == "建 GitHub 分身"))).scalars().all()
    assert len(rows) == 2


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
        a = UserFact(content="用户是甲语母语者,来自甲城", source="auto")        # id1 kept
        c = UserFact(content="用户是甲语母语者,来自甲城地区", source="auto")    # id2 fuzzy-dup, is a target
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
# _to_out BLOCKER anchor: valid_from/superseded_by/provenance must actually be
# populated on the API response, not left null forever.
# ---------------------------------------------------------------------------

async def test_to_out_populates_temporal_fields_via_api(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_API_TOKEN", "test-token")
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "facts.db"))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    import server.config as config
    importlib.reload(config)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'facts.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.orchestrator import memory
    created = await memory.save_facts([{"content": "旧值"}], provenance=_PROV)
    old_id = created[0].id
    winner = await memory.add_manual_fact("新值")
    await execute_supersede("user_facts", winner.id, old_id, provenance=_PROV)

    from server.main import create_app
    app = create_app()
    transport = ASGITransport(app=app)
    auth = {"Authorization": "Bearer test-token"}
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/facts", headers=auth)
        assert r.status_code == 200
        assert all(row["id"] != old_id for row in r.json())  # default excludes superseded

        r2 = await c.get("/api/v1/facts?include_superseded=true", headers=auth)
        assert r2.status_code == 200
        by_id = {row["id"]: row for row in r2.json()}
        assert old_id in by_id
        assert by_id[old_id]["superseded_by"] == winner.id   # _to_out anchor: real value
        assert by_id[old_id]["provenance"] == _PROV
        assert by_id[old_id]["valid_from"] is not None

    await engine.dispose()


# ---------------------------------------------------------------------------
# #12 hermetic regression: record_usage=False still writes zero brain_usage
# (pre-existing invariant), independently confirmed alongside this round's
# facts_text active-only filtering — both must hold post-P1.
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


async def test_hermetic_record_usage_false_and_facts_text_active_only(memdb):
    from server.db.models import BrainUsage, Spawn
    from server.orchestrator import memory
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

    await _seed_superseded_fact(memdb, "旧偏好四四四四")
    text = await memory.facts_text()
    assert "旧偏好四四四四" not in text
