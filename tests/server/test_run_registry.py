"""tests/server/test_run_registry.py"""
import asyncio

import pytest

from server.services import run_registry


@pytest.fixture(autouse=True)
def _clean_registry():
    run_registry._tasks.clear()
    run_registry._by_conversation.clear()
    run_registry._sinks.clear()
    run_registry._recorders.clear()
    yield
    run_registry._tasks.clear()
    run_registry._by_conversation.clear()
    run_registry._sinks.clear()
    run_registry._recorders.clear()


@pytest.mark.asyncio
async def test_register_lookup_unregister():
    async def _work():
        await asyncio.sleep(30)

    task = asyncio.create_task(_work())
    run_registry.register(7, "conv-a", task)
    assert run_registry.get(7) is task
    assert run_registry.active_for("conv-a") == [7]

    run_registry.unregister(7, "conv-a")
    assert run_registry.get(7) is None
    assert run_registry.active_for("conv-a") == []
    task.cancel()


@pytest.mark.asyncio
async def test_cancel_returns_true_once_then_false():
    async def _work():
        await asyncio.sleep(30)

    task = asyncio.create_task(_work())
    run_registry.register(8, "conv-b", task)
    assert run_registry.cancel(8) is True
    # second cancel: task already cancelling — still True until unregistered
    run_registry.unregister(8, "conv-b")
    assert run_registry.cancel(8) is False  # unknown run id
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_cancel_finished_task_returns_false():
    async def _noop():
        return 1

    task = asyncio.create_task(_noop())
    await task
    run_registry.register(9, "conv-c", task)
    assert run_registry.cancel(9) is False  # task already done — nothing to cancel


# --- S3-M2: conversation sink registry + fan-out emit + journal snapshots ---


class _FakeRecorder:
    def __init__(self, events):
        # RunRecorder journal shape: list of (datetime, ev) tuples (run_recorder.py tee)
        self._events = events


def test_attach_detach_lifecycle():
    seen: list[dict] = []
    sink = seen.append

    run_registry.attach_sink("conv-s", sink)
    assert sink in run_registry._sinks["conv-s"]

    run_registry.detach_sink("conv-s", sink)
    assert "conv-s" not in run_registry._sinks  # empty set dropped

    # detach is idempotent — unknown conversation/sink must not raise
    run_registry.detach_sink("conv-s", sink)


def test_make_emit_fans_out_to_all_sinks_and_detach_stops_delivery():
    got_a: list[dict] = []
    got_b: list[dict] = []
    run_registry.attach_sink("conv-f", got_a.append)
    run_registry.attach_sink("conv-f", got_b.append)

    emit = run_registry.make_emit("conv-f")
    emit({"type": "stream_start"})
    assert got_a == [{"type": "stream_start"}]
    assert got_b == [{"type": "stream_start"}]

    run_registry.detach_sink("conv-f", got_b.append)
    emit({"type": "stream_end"})
    assert got_a == [{"type": "stream_start"}, {"type": "stream_end"}]
    assert got_b == [{"type": "stream_start"}]  # detached — no longer delivered

    # no sinks at all — frames drop silently (journal still has them via tee)
    run_registry.detach_sink("conv-f", got_a.append)
    emit({"type": "orphan"})  # must not raise


def test_make_emit_broken_sink_does_not_block_others():
    got: list[dict] = []

    def _broken(ev: dict) -> None:
        raise RuntimeError("dead socket")

    run_registry.attach_sink("conv-x", _broken)
    run_registry.attach_sink("conv-x", got.append)

    emit = run_registry.make_emit("conv-x")
    emit({"type": "stream_chunk"})  # broken sink must not break the dispatch
    assert got == [{"type": "stream_chunk"}]


@pytest.mark.asyncio
async def test_register_recorder_roundtrip_and_unregister_pops():
    async def _work():
        await asyncio.sleep(30)

    rec = _FakeRecorder([])
    task = asyncio.create_task(_work())
    run_registry.register(11, "conv-r", task, recorder=rec)
    assert run_registry._recorders[11] is rec

    run_registry.unregister(11, "conv-r")
    assert 11 not in run_registry._recorders
    task.cancel()


@pytest.mark.asyncio
async def test_journal_snapshots_run_id_order_copies_and_skips_missing_recorder():
    import datetime as _dt

    async def _work():
        await asyncio.sleep(30)

    now = _dt.datetime.utcnow()
    rec_hi = _FakeRecorder([(now, {"type": "stream_start"}), (now, {"type": "stream_end"})])
    rec_lo = _FakeRecorder([(now, {"type": "tool_call"})])

    t1 = asyncio.create_task(_work())
    t2 = asyncio.create_task(_work())
    t3 = asyncio.create_task(_work())
    # register out of order; run 30 has NO recorder → skipped
    run_registry.register(42, "conv-j", t1, recorder=rec_hi)
    run_registry.register(30, "conv-j", t2)
    run_registry.register(7, "conv-j", t3, recorder=rec_lo)

    snaps = run_registry.journal_snapshots("conv-j")
    assert snaps == [
        (7, [{"type": "tool_call"}]),
        (42, [{"type": "stream_start"}, {"type": "stream_end"}]),
    ]

    # copies: mutating the snapshot list must not touch the recorder journal
    snaps[1][1].append({"type": "injected"})
    assert len(rec_hi._events) == 2

    # other conversations: nothing active → empty list
    assert run_registry.journal_snapshots("conv-unknown") == []

    for t in (t1, t2, t3):
        t.cancel()
