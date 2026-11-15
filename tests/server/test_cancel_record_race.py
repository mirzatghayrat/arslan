"""v0.1.64: a window closed while its turn is still finishing. The turn is cancelled and its cancel record is written
by a detached task (task_service._run), which outlives the turn lock. Until it commits, the task is still "running",
and the conversation's next turn would hit the one-active-turn index and be refused with `task_version_conflict`: a
window reopened and typed into at once lost its message. The next turn now waits for that record (bounded), and retries
a refused start once."""
import asyncio
import threading
import time

import pytest
from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ArslanMessage
from server.db.task_models import CompanionTask
from server.services import approvals, task_context, task_repository, task_service
from tests.server import test_cap8b_memory_import as base
from tests.server.conftest import build_ws_client
from tests.server.test_cap8b_registered_tool import _Model, _turn_on

post_turn, no_judge = base.post_turn, base.no_judge


@pytest.fixture
def window_client(tmp_path, monkeypatch, portal):
    approvals._reset_for_tests()
    yield build_ws_client(portal, tmp_path, monkeypatch, db_name="race.db")
    approvals._reset_for_tests()


def _frames_until_end(window, seconds=15.0):
    """Frames until `stream_end` or an error frame, read on a thread so a turn that never ends fails here in
    `seconds` rather than at the 120 s timeout. Returns (frames, still_waiting)."""
    frames = []

    def read():
        try:
            for _ in range(80):
                frame = window.receive_json()
                frames.append(frame)
                if frame.get("type") in ("stream_end", "error"):
                    return
        except Exception:  # noqa: BLE001 — the socket closed under the reader: the frames so far say why
            return
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(seconds)
    return frames, reader.is_alive()


async def _phases():
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(CompanionTask).order_by(CompanionTask.created_at))).scalars().all()
    return [row.phase for row in rows]


async def _user_messages():
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(ArslanMessage).where(ArslanMessage.role == "user"))).scalars().all()
    return [row.content for row in rows]


def _cut_short(window_client, portal, monkeypatch, held_record):
    """A turn whose window closes after its reply, while the task's finish is still running; its cancel record is
    `held_record`'s to write."""
    real_finish = task_repository.TaskRepository.finish
    held = {"finish": False}

    async def finish(self, *args, **kwargs):
        if not held["finish"]:
            held["finish"] = True
            await asyncio.Event().wait()          # cancelled when the window closes
        return await real_finish(self, *args, **kwargs)
    monkeypatch.setattr(task_repository.TaskRepository, "finish", finish)
    monkeypatch.setattr(task_service, "_record_cancel", held_record)
    with window_client.websocket_connect("/ws/arslan/main") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "Hi"})
        frames, waiting = _frames_until_end(window)
        assert not waiting and frames[-1]["type"] == "stream_end", frames
        deadline = time.monotonic() + 10
        while not held["finish"]:
            assert time.monotonic() < deadline, "the turn never reached its finish"
            time.sleep(0.02)
    assert portal.call(_phases)[-1] == "running"   # the record is not written yet


def test_the_next_turn_starts_after_the_cancel_record(window_client, portal, post_turn, monkeypatch):
    """The record is let go once the next turn has begun (its context loaded), and then lingers while that turn could
    create its task. The task is created only after the earlier one reads "cancelled", and the turn answers."""
    _turn_on(monkeypatch, _Model("Hello.", "It is noon."))
    real_record, real_load = task_service._record_cancel, task_context.load
    gates = {}
    seen_at_create = []

    def gate(name):
        return gates.setdefault(name, asyncio.Event())

    async def held_record(task_id):
        await gate("next turn began").wait()
        try:      # long enough for a start that does not wait to create its task first
            await asyncio.wait_for(gate("created").wait(), timeout=2)
        except TimeoutError:
            pass
        return await real_record(task_id)

    async def load(*args, **kwargs):
        gate("next turn began").set()
        return await real_load(*args, **kwargs)

    real_create = task_repository.TaskRepository.create

    async def create(self, *args, **kwargs):
        seen_at_create.append(await _phases())
        gate("created").set()
        return await real_create(self, *args, **kwargs)
    _cut_short(window_client, portal, monkeypatch, held_record)
    monkeypatch.setattr(task_context, "load", load)
    monkeypatch.setattr(task_repository.TaskRepository, "create", create)
    with window_client.websocket_connect("/ws/arslan/main") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "What is the time?"})
        frames, waiting = _frames_until_end(window)
    assert not waiting, f"the next turn never ended: {frames}"
    assert seen_at_create[0] == ["cancelled"], seen_at_create
    assert frames[-1]["type"] == "stream_end", frames
    assert portal.call(_phases)[0] == "cancelled"
    assert "What is the time?" in portal.call(_user_messages)


def test_a_record_that_never_commits_costs_a_bounded_wait_and_a_resend(window_client, portal, post_turn, monkeypatch):
    """The wait has a bound, and so has the retry. A start still refused after both says so: the message was not
    stored, and the frame is `task_version_conflict`, which the window shows as "this one did not start. Send it
    again" (web chatTaskErrorKey). The text is the window's to resend; the server keeps nothing of it."""
    _turn_on(monkeypatch, _Model("Hello.", "It is noon."))
    monkeypatch.setattr(task_service, "CANCEL_RECORD_WAIT_S", 0.3)
    stuck = {}

    async def never_written(task_id):
        stuck["event"] = asyncio.Event()
        await stuck["event"].wait()
    _cut_short(window_client, portal, monkeypatch, never_written)
    started = time.monotonic()
    with window_client.websocket_connect("/ws/arslan/main") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "What is the time?"})
        frames, waiting = _frames_until_end(window, seconds=10)
    elapsed = time.monotonic() - started

    async def let_go():
        stuck["event"].set()
    portal.call(let_go)
    assert not waiting, f"the next turn waited on the record without a bound: {frames}"
    assert frames[-1] == {"type": "error", "code": "TASK_REVIEW_REQUIRED", "message": "task_version_conflict",
                          "recoverable": True}, frames
    assert elapsed < 5, elapsed
    assert "What is the time?" not in portal.call(_user_messages)


async def _paused_task(conversation_id: str) -> int:
    """An earlier task of the conversation, paused part-way and so resumable. Returns its version."""
    async def attempt(emit):
        task_service.current().pause_reason = "task_no_progress"
        return "Partial evidence, not completion"
    await task_context.execute_entry(conversation_id, "Check the report", lambda event: None, attempt,
                                     task_id="paused-task")
    async with task_repository.repository() as repo:
        row = await repo.get("paused-task")
    assert row.phase == "waiting_user"
    return row.version


def test_a_resume_starts_after_the_cancel_record(window_client, portal, post_turn, monkeypatch):
    """Resume pressed in the reopened window, on an earlier paused task, while the closed window's turn is still
    writing its cancel record: the resume waits for it, and the resumed turn answers."""
    _turn_on(monkeypatch, _Model("Hello.", "Checked."))
    version = portal.call(_paused_task, "main")
    real_record, real_load, real_start = task_service._record_cancel, task_context.load, task_repository.TaskRepository.start
    gates, seen_at_start = {}, []

    def gate(name):
        return gates.setdefault(name, asyncio.Event())

    async def held_record(task_id):
        await gate("resume began").wait()
        try:      # long enough for a resume that does not wait to start first
            await asyncio.wait_for(gate("started").wait(), timeout=2)
        except TimeoutError:
            pass
        return await real_record(task_id)
    _cut_short(window_client, portal, monkeypatch, held_record)

    async def load(*args, **kwargs):
        gate("resume began").set()
        return await real_load(*args, **kwargs)

    async def start(self, task_id, *args, **kwargs):
        if task_id == "paused-task":
            seen_at_start.append(await _phases())
            gate("started").set()
        return await real_start(self, task_id, *args, **kwargs)
    monkeypatch.setattr(task_context, "load", load)
    monkeypatch.setattr(task_repository.TaskRepository, "start", start)
    with window_client.websocket_connect("/ws/arslan/main") as window:
        window.receive_json()
        window.send_json({"type": "resume_task", "task_id": "paused-task", "expected_version": version})
        frames, waiting = _frames_until_end(window)
    assert not waiting, f"the resumed turn never ended: {frames}"
    assert seen_at_start[0] == ["waiting_user", "cancelled"], seen_at_start
    assert frames[-1]["type"] == "stream_end", frames


def test_a_start_refused_once_is_retried(window_client, portal, post_turn, monkeypatch):
    """A start refused once (the record committed just after the wait, or another writer held the lock) is tried
    again, and the turn answers."""
    _turn_on(monkeypatch, _Model("Hello."))
    real_start, refused = task_repository.TaskRepository.start, []

    async def start(self, *args, **kwargs):
        if not refused:
            refused.append(1)
            raise task_repository.TaskError("task_version_conflict")
        return await real_start(self, *args, **kwargs)
    monkeypatch.setattr(task_repository.TaskRepository, "start", start)
    with window_client.websocket_connect("/ws/arslan/main") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "Hi"})
        frames, waiting = _frames_until_end(window)
    assert refused and not waiting and frames[-1]["type"] == "stream_end", frames
    assert portal.call(_phases) != []
