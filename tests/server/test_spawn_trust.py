"""spawn_trust.trust: deterministic green/trusted band from feedback aggregation."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Feedback, Spawn


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'trust.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


async def _make_spawn(maker, spawn_id=1):
    async with maker() as s:
        s.add(Spawn(id=spawn_id, name=f"x{spawn_id}", domain_category="d", system_prompt="p"))
        await s.commit()


@pytest.mark.asyncio
async def test_new_spawn_is_green(maker):
    from server.services import spawn_trust

    await _make_spawn(maker, 1)
    async with maker() as s:
        t = await spawn_trust.trust(s, 1)
    assert t["band"] == "green"
    assert t["tasks"] == 0
    assert t["accept_rate"] == 0.0


@pytest.mark.asyncio
async def test_spawn_graduates_to_trusted(maker):
    from server.services import spawn_trust

    await _make_spawn(maker, 1)
    async with maker() as s:
        for i in range(3):
            s.add(Feedback(spawn_id=1, session_id=f"c{i}", user_action="thumbs_up",
                           quality_signal=1, message_id=i))
        await s.commit()
    async with maker() as s:
        t = await spawn_trust.trust(s, 1)
    assert t["band"] == "trusted"
    assert t["tasks"] == 3
    assert t["accept_rate"] == 1.0


@pytest.mark.asyncio
async def test_low_accept_rate_stays_green(maker):
    from server.services import spawn_trust

    await _make_spawn(maker, 1)
    async with maker() as s:
        # 3 distinct sessions (>= MIN_TASKS) but mostly thumbs_down:
        # 1 up + 3 down -> accept_rate 0.25 < 0.6 -> green.
        s.add(Feedback(spawn_id=1, session_id="c0", user_action="thumbs_up",
                       quality_signal=1, message_id=0))
        s.add(Feedback(spawn_id=1, session_id="c0", user_action="thumbs_down",
                       quality_signal=-1, message_id=1))
        s.add(Feedback(spawn_id=1, session_id="c1", user_action="thumbs_down",
                       quality_signal=-1, message_id=2))
        s.add(Feedback(spawn_id=1, session_id="c2", user_action="thumbs_down",
                       quality_signal=-1, message_id=3))
        await s.commit()
    async with maker() as s:
        t = await spawn_trust.trust(s, 1)
    assert t["band"] == "green"
    assert t["tasks"] == 3
    assert t["accept_rate"] == 0.25


@pytest.mark.asyncio
async def test_below_min_tasks_stays_green(maker):
    """Perfect accept rate but < MIN_TASKS distinct sessions -> still green."""
    from server.services import spawn_trust

    await _make_spawn(maker, 1)
    async with maker() as s:
        for i in range(2):
            s.add(Feedback(spawn_id=1, session_id=f"c{i}", user_action="thumbs_up",
                           quality_signal=1, message_id=i))
        await s.commit()
    async with maker() as s:
        t = await spawn_trust.trust(s, 1)
    assert t["band"] == "green"
    assert t["tasks"] == 2
    assert t["accept_rate"] == 1.0
