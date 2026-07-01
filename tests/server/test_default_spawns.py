import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'d.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    anyio.run(_init)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def test_to_summary_carries_is_default():
    from server.services import spawn_service
    sp = Spawn(id=1, name="B", domain_category="x", capabilities=[], system_prompt="x", is_default=True)
    assert spawn_service.to_summary(sp).is_default is True


@pytest.mark.asyncio
async def test_delete_rejects_builtin(maker):
    from server.services import spawn_service
    async with maker() as s:
        sp = Spawn(name="Built-In", domain_category="x", capabilities=[], system_prompt="x", is_default=True)
        s.add(sp); await s.commit(); await s.refresh(sp)
        with pytest.raises(spawn_service.BuiltInSpawnError):
            await spawn_service.delete_spawn(s, sp.id)
        assert await s.get(Spawn, sp.id) is not None   # not deleted


@pytest.mark.asyncio
async def test_delete_allows_normal_spawn(maker):
    from server.services import spawn_service
    async with maker() as s:
        sp = Spawn(name="Normal", domain_category="x", capabilities=[], system_prompt="x", is_default=False)
        s.add(sp); await s.commit(); await s.refresh(sp)
        assert await spawn_service.delete_spawn(s, sp.id) is True


@pytest.mark.asyncio
async def test_seed_default_spawns_creates_missing_then_idempotent(maker, monkeypatch):
    from server.services import default_spawns, spawn_service
    calls: list[tuple[str, bool]] = []

    async def fake_create(draft, differentiation=None, *, is_default=False):
        calls.append((draft["name"], is_default))
        async with maker() as s:  # insert so the next run's name-check sees it
            s.add(Spawn(name=draft["name"], domain_category="x", capabilities=[],
                        system_prompt="x", is_default=is_default))
            await s.commit()
        return (1, draft["name"], {}, "")

    monkeypatch.setattr(spawn_service, "create_from_draft", fake_create)
    await default_spawns.seed_default_spawns()
    assert [n for n, _ in calls] == [s["name"] for s in default_spawns.DEFAULT_SPAWNS]
    assert all(is_def for _, is_def in calls)          # every default is is_default=True
    n1 = len(calls)
    await default_spawns.seed_default_spawns()          # second boot: all exist → no new creates
    assert len(calls) == n1
