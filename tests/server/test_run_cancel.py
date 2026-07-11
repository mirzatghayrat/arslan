"""S3-M1 Task 3: cancel mid-dispatch — _dispatch_spawn runs as a registered
cancellable task. run_registry.cancel(run_id) must finalize the Run as
'cancelled' (never scored → never corpus), persist the streamed partial as a
spawn_summary, emit a run_cancelled frame, and let the OUTER coroutine return
normally (the WS turn survives the cancel)."""

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import ArslanMessage, Base, Run, Spawn
from server.orchestrator import arslan
from server.services import run_registry
from server.ws import arslan as ws_arslan


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


async def _seed_spawn(Session) -> int:
    async with Session() as db:
        spawn = Spawn(name="S", domain_category="general", system_prompt="sp")
        db.add(spawn)
        await db.commit()
        await db.refresh(spawn)
        return spawn.id


async def _aw(v):
    return v


async def _drive_cancelled_turn(memdb, monkeypatch):
    """Dispatch a slow spawn turn, cancel it mid-stream, await the outer coroutine."""
    spawn_id = await _seed_spawn(memdb)
    started = asyncio.Event()

    async def slow_dispatch(conversation_id, **kwargs):
        kwargs["on_chunk"]("partial ")   # some output already streamed
        started.set()
        await asyncio.sleep(30)          # cancelled long before this completes
        raise AssertionError("dispatch was not cancelled")

    monkeypatch.setattr(arslan.dispatcher, "dispatch", slow_dispatch)
    # No LLM in this test: the routing announcement is orthogonal to cancellation.
    monkeypatch.setattr(arslan, "_route_announcement", lambda *a, **k: _aw(None))
    frames: list[dict] = []

    turn = asyncio.create_task(arslan.dispatch_spawn(
        "conv-cancel", spawn_id, "test brief", frames.append, user_message="u"))
    await asyncio.wait_for(started.wait(), 5)

    run_id = next(f["run_id"] for f in frames if f["type"] == "stream_start")
    assert run_registry.cancel(run_id) is True
    await asyncio.wait_for(turn, 5)      # outer coroutine survives the cancel
    return run_id, frames


async def test_cancel_mid_dispatch_finalizes_cancelled(memdb, monkeypatch):
    run_id, frames = await _drive_cancelled_turn(memdb, monkeypatch)

    async with memdb() as db:
        run = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one()
    assert run.status == "cancelled"
    assert any(f["type"] == "run_cancelled" for f in frames)
    assert run_registry.get(run_id) is None  # unregistered


async def test_cancel_persists_streamed_partial(memdb, monkeypatch):
    run_id, frames = await _drive_cancelled_turn(memdb, monkeypatch)

    async with memdb() as db:
        rows = (await db.execute(select(ArslanMessage).where(
            ArslanMessage.role == "spawn_summary"))).scalars().all()
    assert len(rows) == 1
    assert "partial " in (rows[0].display_content or "")
    assert "已中断" in (rows[0].display_content or "")
    cancelled = next(f for f in frames if f["type"] == "run_cancelled")
    assert cancelled["run_id"] == run_id
    assert cancelled.get("message_id") == rows[0].id


async def test_cancel_during_announcement_finalizes_cancelled(memdb, monkeypatch):
    """Review I3: a cancel landing BEFORE streaming (during the routing-announcement
    LLM call) must still finalize the Run as 'cancelled' — never leave the row rotting
    at 'recording' until the next boot reap."""
    spawn_id = await _seed_spawn(memdb)
    entered = asyncio.Event()

    async def slow_announcement(*a, **k):
        entered.set()
        await asyncio.sleep(30)

    async def unreachable_dispatch(*a, **k):
        raise AssertionError("dispatch must not be reached on a pre-stream cancel")

    monkeypatch.setattr(arslan, "_route_announcement", slow_announcement)
    monkeypatch.setattr(arslan.dispatcher, "dispatch", unreachable_dispatch)
    frames: list[dict] = []

    turn = asyncio.create_task(arslan.dispatch_spawn(
        "conv-pre", spawn_id, "test brief", frames.append, user_message="u"))
    await asyncio.wait_for(entered.wait(), 5)

    run_ids = run_registry.active_for("conv-pre")
    assert len(run_ids) == 1
    assert run_registry.cancel(run_ids[0]) is True
    await asyncio.wait_for(turn, 5)      # outer coroutine survives the cancel

    async with memdb() as db:
        run = (await db.execute(select(Run).where(Run.id == run_ids[0]))).scalar_one()
    assert run.status == "cancelled"
    assert any(f["type"] == "run_cancelled" for f in frames)
    assert run_registry.get(run_ids[0]) is None


def test_to_frame_keeps_run_id_on_stream_start():
    """The WS layer REBUILDS stream_start frames — without passing run_id through,
    the client would never receive its cancel handle (silent-drop regression pin)."""
    frame = ws_arslan._to_frame(
        {"type": "stream_start", "source": "spawn", "spawn_id": 3, "run_id": 42})
    assert frame["run_id"] == 42
    bare = ws_arslan._to_frame({"type": "stream_start", "source": "arslan"})
    assert "run_id" not in bare
