"""Deterministic supersede executor: pointer write, undo, guards, both session modes.

Covers server/services/memory_temporal.py (P1 spec). Execution is a single pointer
write (old.superseded_by = new_id) — the old row is never deleted. All rejections are
structured SupersedeError(code, detail); provenance is mandatory (programmer guard).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Learning, UserFact

_PROV = {"source_kind": "test"}


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'temporal.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


async def _seed_facts(maker, n: int) -> list[int]:
    """Insert n bare UserFact rows and return their ids in insertion order."""
    async with maker() as s:
        rows = [UserFact(content=f"fact {i}") for i in range(n)]
        s.add_all(rows)
        await s.commit()
        return [r.id for r in rows]


# ---------------------------------------------------------------------------
# Core supersede + undo
# ---------------------------------------------------------------------------


async def test_supersede_writes_pointer_and_keeps_old_row(maker):
    from server.services.memory_temporal import execute_supersede

    old_id, new_id = await _seed_facts(maker, 2)

    await execute_supersede("user_facts", new_id, old_id, provenance=_PROV)

    async with maker() as s:
        old_row = await s.get(UserFact, old_id)
        new_row = await s.get(UserFact, new_id)
    assert old_row is not None  # old row never deleted
    assert old_row.superseded_by == new_id
    assert new_row.superseded_by is None


async def test_undo_supersede_restores_active(maker):
    from server.services.memory_temporal import execute_supersede, undo_supersede

    old_id, new_id = await _seed_facts(maker, 2)
    await execute_supersede("user_facts", new_id, old_id, provenance=_PROV)

    await undo_supersede("user_facts", old_id, provenance=_PROV)

    async with maker() as s:
        old_row = await s.get(UserFact, old_id)
    assert old_row.superseded_by is None


async def test_undo_supersede_not_superseded_raises(maker):
    from server.services.memory_temporal import SupersedeError, undo_supersede

    (lone_id,) = await _seed_facts(maker, 1)

    with pytest.raises(SupersedeError) as exc:
        await undo_supersede("user_facts", lone_id, provenance=_PROV)
    assert exc.value.code == "not_superseded"


async def test_supersede_works_for_learnings_table(maker):
    from server.services.memory_temporal import execute_supersede

    async with maker() as s:
        old = Learning(content="old learning", source_kind="distill", source_ref={"x": 1})
        new = Learning(content="new learning", source_kind="distill", source_ref={"x": 2})
        s.add_all([old, new])
        await s.commit()
        old_id, new_id = old.id, new.id

    await execute_supersede("learnings", new_id, old_id, provenance=_PROV)

    async with maker() as s:
        old_row = await s.get(Learning, old_id)
    assert old_row.superseded_by == new_id


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


async def test_double_supersede_rejected(maker):
    from server.services.memory_temporal import SupersedeError, execute_supersede

    old_id, new_id, other_id = await _seed_facts(maker, 3)
    await execute_supersede("user_facts", new_id, old_id, provenance=_PROV)

    with pytest.raises(SupersedeError) as exc:
        await execute_supersede("user_facts", other_id, old_id, provenance=_PROV)
    assert exc.value.code == "already_superseded"


async def test_self_supersede_rejected(maker):
    from server.services.memory_temporal import SupersedeError, execute_supersede

    (lone_id,) = await _seed_facts(maker, 1)

    with pytest.raises(SupersedeError) as exc:
        await execute_supersede("user_facts", lone_id, lone_id, provenance=_PROV)
    assert exc.value.code == "self_supersede"


async def test_cross_supersede_after_a_supersedes_b_is_rejected(maker):
    """A supersedes B, then B tries to supersede A back.

    Guard order makes this hit new_is_superseded (B, the would-be new superseder,
    is itself already superseded) rather than the bounded cycle walk — the cycle
    guard is intentional inert-by-design defense-in-depth (see module docstring:
    new_is_superseded fires first, so cursor.superseded_by is always None when the
    chain walk would start, making it currently unreachable). We assert rejection
    happened, not a specific code, per the brief.
    """
    from server.services.memory_temporal import SupersedeError, execute_supersede

    a_id, b_id = await _seed_facts(maker, 2)
    await execute_supersede("user_facts", a_id, b_id, provenance=_PROV)  # A supersedes B

    with pytest.raises(SupersedeError) as exc:
        await execute_supersede("user_facts", b_id, a_id, provenance=_PROV)  # B -> A
    # Recording the actual code for documentation purposes (not hard-asserting a
    # specific value beyond "a structured rejection occurred").
    assert exc.value.code  # non-empty structured code
    assert exc.value.code == "new_is_superseded"  # actual current behavior


async def test_dangling_new_rejected(maker):
    from server.services.memory_temporal import SupersedeError, execute_supersede

    (old_id,) = await _seed_facts(maker, 1)

    with pytest.raises(SupersedeError) as exc:
        await execute_supersede("user_facts", 999999, old_id, provenance=_PROV)
    assert exc.value.code == "dangling_new"


async def test_dangling_old_rejected(maker):
    from server.services.memory_temporal import SupersedeError, execute_supersede

    (new_id,) = await _seed_facts(maker, 1)

    with pytest.raises(SupersedeError) as exc:
        await execute_supersede("user_facts", new_id, 999999, provenance=_PROV)
    assert exc.value.code == "dangling_old"


async def test_missing_provenance_raises(maker):
    from server.services.memory_temporal import SupersedeError, execute_supersede

    old_id, new_id = await _seed_facts(maker, 2)

    with pytest.raises(SupersedeError) as exc:
        await execute_supersede("user_facts", new_id, old_id, provenance={})
    assert exc.value.code == "missing_provenance"


async def test_bad_table_raises(maker):
    from server.services.memory_temporal import SupersedeError, execute_supersede

    with pytest.raises(SupersedeError) as exc:
        await execute_supersede("not_a_real_table", 1, 2, provenance=_PROV)
    assert exc.value.code == "bad_table"


# ---------------------------------------------------------------------------
# db= passed-in mode: caller's transaction owns the commit
# ---------------------------------------------------------------------------


async def test_db_passed_in_mode_runs_guards(maker):
    """A seeded already-superseded old row must still trip already_superseded when
    execute_supersede runs inside a caller-supplied session (not just db=None)."""
    from server.services.memory_temporal import SupersedeError, execute_supersede

    a_id, b_id, c_id = await _seed_facts(maker, 3)

    async with maker() as seed:
        b_row = await seed.get(UserFact, b_id)
        b_row.superseded_by = a_id
        await seed.commit()

    async with maker() as db:
        with pytest.raises(SupersedeError) as exc:
            await execute_supersede("user_facts", c_id, b_id, provenance=_PROV, db=db)
    assert exc.value.code == "already_superseded"


async def test_db_passed_in_mode_success_caller_commits_no_premature_commit(maker):
    """execute_supersede(db=session) must not commit itself: the pointer write should
    be invisible to a fresh session until the caller commits, and visible after."""
    from server.services.memory_temporal import execute_supersede

    old_id, new_id = await _seed_facts(maker, 2)

    async with maker() as db:
        await execute_supersede("user_facts", new_id, old_id, provenance=_PROV, db=db)

        # Not yet committed by execute_supersede — a fresh session must not see it.
        async with maker() as peek:
            still_active = await peek.get(UserFact, old_id)
        assert still_active.superseded_by is None

        await db.commit()  # caller owns the commit

    async with maker() as verify:
        row = await verify.get(UserFact, old_id)
    assert row.superseded_by == new_id


# ---------------------------------------------------------------------------
# initiate_supersede: thin Tier-1 seam
# ---------------------------------------------------------------------------


async def test_initiate_supersede_delegates_to_execute_supersede(maker):
    from server.services.memory_temporal import initiate_supersede

    old_id, new_id = await _seed_facts(maker, 2)

    await initiate_supersede("user_facts", new_id, old_id, provenance=_PROV)

    async with maker() as s:
        old_row = await s.get(UserFact, old_id)
    assert old_row.superseded_by == new_id
