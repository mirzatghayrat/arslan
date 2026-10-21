"""memory_temporal under memory v2: provenance is still mandatory (a programmer guard), then every supersede
or undo refuses with versioned_review_required. 0.1.63 C2a-2 removed the v1 pointer-rewrite tests with the
rewrite itself.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, UserFact

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
# Guards
# ---------------------------------------------------------------------------


async def test_missing_provenance_raises(maker):
    from server.services.memory_temporal import SupersedeError, execute_supersede

    old_id, new_id = await _seed_facts(maker, 2)

    with pytest.raises(SupersedeError) as exc:
        await execute_supersede("user_facts", new_id, old_id, provenance={})
    assert exc.value.code == "missing_provenance"


async def test_with_provenance_both_refuse_for_versioned_review(maker):
    from server.services.memory_temporal import SupersedeError, execute_supersede, undo_supersede
    for call in (execute_supersede("user_facts", 2, 1, provenance={"source_kind": "test"}),
                 undo_supersede("learnings", 1, provenance={"source_kind": "test"})):
        with pytest.raises(SupersedeError) as caught:
            await call
        assert caught.value.code == "versioned_review_required"
