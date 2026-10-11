"""`desktop_status.when_work_ends` (Hands v2 §15 A18): a callback attached to the work in flight runs
when that work ends — normally, with an error, or cancelled — and a callback's own error never
breaks the work's exit or the other callbacks."""
import asyncio

import pytest

from server.services import desktop_status


def test_a_callback_runs_when_the_work_ends_normally():
    ran = []
    with desktop_status.working("c1", kind="turn"):
        assert desktop_status.when_work_ends(lambda: ran.append("back"))
        assert ran == [], "not before the work ends"
    assert ran == ["back"]


def test_a_callback_runs_when_the_work_raises():
    ran = []
    with pytest.raises(RuntimeError):
        with desktop_status.working("c1", kind="job"):
            desktop_status.when_work_ends(lambda: ran.append("back"))
            raise RuntimeError("the work failed")
    assert ran == ["back"]


async def test_a_callback_runs_when_the_work_is_cancelled():
    ran, inside = [], asyncio.Event()

    async def work():
        with desktop_status.working("c1", kind="turn"):
            desktop_status.when_work_ends(lambda: ran.append("back"))
            inside.set()
            await asyncio.sleep(30)
    task = asyncio.create_task(work())
    await inside.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ran == ["back"]


def test_a_failing_callback_does_not_break_the_exit_or_the_others(caplog):
    ran = []

    def broken():
        raise ValueError("broken callback")
    with desktop_status.working("c1", kind="turn"):
        desktop_status.when_work_ends(broken, key="a")
        desktop_status.when_work_ends(lambda: ran.append("b"), key="b")
    assert ran == ["b"]
    assert "when_work_ends callback failed" in caplog.text


def test_one_callback_per_key_and_nothing_outside_work():
    ran = []
    assert desktop_status.when_work_ends(lambda: ran.append("x")) is False, "no work in flight"
    with desktop_status.working("c1", kind="turn"):
        desktop_status.when_work_ends(lambda: ran.append("first"), key="hands.visit")
        desktop_status.when_work_ends(lambda: ran.append("second"), key="hands.visit")
    assert ran == ["second"]


def test_callbacks_belong_to_their_own_work():
    ran = []
    with desktop_status.working("c1", kind="turn"):
        with desktop_status.working("c1", kind="job"):
            desktop_status.when_work_ends(lambda: ran.append("job"))
        assert ran == ["job"], "the job ended, not the turn"
        desktop_status.when_work_ends(lambda: ran.append("turn"))
    assert ran == ["job", "turn"]
