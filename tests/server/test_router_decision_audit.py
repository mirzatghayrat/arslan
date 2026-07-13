"""RouterDecision is an append-only audit log: rows must survive spawn deletion
with the original spawn_id intact (not nulled, not cascaded away)."""
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, RouterDecision, Spawn
from server.services import spawn_service


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'audit.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        # Enforce FKs so any accidental FK on spawn_id would blow up here.
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_router_decision_survives_spawn_deletion(maker):
    """After a spawn is deleted, its RouterDecision rows must still exist with
    the original spawn_id value — they are historical records, not live links."""
    # 1. Create a spawn and a RouterDecision pointing at it.
    async with maker() as s:
        s.add(Spawn(id=42, name="audit-target", domain_category="test", system_prompt="p"))
        await s.commit()
        s.add(
            RouterDecision(
                conversation_id="c1",
                user_message="do something",
                action="route",
                spawn_id=42,
                reason="routed to audit-target",
            )
        )
        await s.commit()

    # 2. Delete the spawn via the real service (PRAGMA foreign_keys=ON is active).
    async with maker() as s:
        ok = await spawn_service.delete_spawn(s, 42)
    assert ok is True

    # 3. The spawn must be gone.
    async with maker() as s:
        assert (await s.get(Spawn, 42)) is None

    # 4. The RouterDecision row must still exist with spawn_id=42 (not nulled, not deleted).
    async with maker() as s:
        rows = (await s.execute(select(RouterDecision))).scalars().all()
    assert len(rows) == 1
    dec = rows[0]
    assert dec.spawn_id == 42, (
        f"RouterDecision.spawn_id was modified on spawn deletion (got {dec.spawn_id!r}); "
        "it must retain the historical value as an unconstrained audit reference."
    )
    assert dec.action == "route"
    assert dec.conversation_id == "c1"
