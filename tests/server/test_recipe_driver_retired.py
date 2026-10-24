"""C7b-3 (v0.1.63): recipes were removed; a task saved with a recipe driver fails closed.

`recipes.execute` was the only thing that created recipe-driven tasks, and the resume path
(`ws/arslan.py` resume_task -> `task_service.resume_turn`) was the one place the chat path
still reached it. ⓪Plan's conditions for removing that branch, pinned here:

1. every driver kind that remains (host, background, expert) resumes exactly as before;
2. an old recipe-driven task fails closed with `task_invalid_driver` and is left untouched
   (no new attempt, same version, same phase) — never a 500 or a crash;
3. the `resume_task` WS handler turns that refusal into a recoverable error frame and the
   socket keeps working.
"""
import pytest
from sqlalchemy import select

from arslan.execution_budget import current as budget
from server.db.models import CompanionTask, TaskAttempt
from server.services import personal_context as pc, task_context, task_service
from server.services.task_repository import TaskError, repository

_RECIPE_DRIVER = {"kind": "recipe", "id": 3, "version_id": 1}


@pytest.fixture
def active_context(monkeypatch):
    async def load(cid, **kwargs):
        return pc.TaskMemoryContext(task_id="entry-task", run_id="initial", conversation_id=cid,
                                    no_learning=True, query=kwargs.get("retrieval_query") or kwargs.get("user_message", ""))
    monkeypatch.setattr(task_context, "load", load)


async def _paused_task(conversation_id: str, driver: dict | None) -> int:
    """A task paused part-way, as one is left after a stopped attempt. Returns its version."""
    async def attempt(emit):
        budget().tool()
        task_service.current().pause_reason = "task_no_progress"
        return "Partial evidence, not completion"
    await task_context.execute_entry(conversation_id, "Verify the supplied artifact", lambda event: None,
                                     attempt, driver=driver)
    async with repository() as repo:
        row = await repo.get("entry-task")
        assert row.phase == "waiting_user"
        return row.version


async def _make_it_an_old_recipe_task(maker) -> None:
    """New code cannot create a recipe-driven task any more (checked_driver refuses it), so
    write the driver straight into the stored row, the way an old database holds it."""
    async with maker() as db:
        row = await db.get(CompanionTask, "entry-task")
        row.privacy = {**(row.privacy or {}), "driver": dict(_RECIPE_DRIVER)}
        await db.commit()


@pytest.mark.parametrize("driver", [None, {"kind": "host"}, {"kind": "background"}, {"kind": "expert", "id": 7}])
async def test_every_remaining_driver_kind_resumes_as_before(execution_db, active_context, monkeypatch, driver):
    version = await _paused_task("entry", driver)
    from server.orchestrator import arslan
    calls = []

    async def answer(conversation_id, user_message, emit, **kwargs):
        calls.append((conversation_id, user_message))
        budget().tool()
        return "Verified."
    monkeypatch.setattr(arslan, "_handle_answer", answer)

    await task_service.resume_turn("entry-task", version, "entry", lambda event: None)

    assert calls == [("entry", "Verify the supplied artifact")]
    async with execution_db() as db:
        assert len((await db.scalars(select(TaskAttempt))).all()) == 2
        row = await db.get(CompanionTask, "entry-task")
        assert row.phase == "succeeded" and row.budget["used"]["tool_calls"] == 2


async def test_an_old_recipe_task_fails_closed_and_is_left_untouched(execution_db, active_context, monkeypatch):
    version = await _paused_task("entry", None)
    await _make_it_an_old_recipe_task(execution_db)
    from server.orchestrator import arslan

    async def answer(*a, **k):
        raise AssertionError("a recipe task must not turn into an Arslan turn either")
    monkeypatch.setattr(arslan, "_handle_answer", answer)

    with pytest.raises(TaskError, match="task_invalid_driver"):
        await task_service.resume_turn("entry-task", version, "entry", lambda event: None)

    async with execution_db() as db:
        assert len((await db.scalars(select(TaskAttempt))).all()) == 1      # no new attempt
        row = await db.get(CompanionTask, "entry-task")
        assert row.version == version and row.phase == "waiting_user"
        assert row.pause_reason == "task_no_progress"
        assert row.privacy["driver"] == _RECIPE_DRIVER                     # kept as data


def test_resume_task_over_the_socket_reports_the_refusal_and_keeps_the_socket(tmp_path, monkeypatch, portal,
                                                                             active_context):
    from server.db import session as db_session
    from tests.server.conftest import build_ws_client

    client = build_ws_client(portal, tmp_path, monkeypatch, db_name="recipe_retired.db")
    version = portal.call(_paused_task, "entry", None)
    portal.call(_make_it_an_old_recipe_task, db_session.AsyncSessionLocal)

    with client.websocket_connect("/ws/arslan/entry") as ws:
        ws.receive_json()                                   # history frame on connect
        ws.send_json({"type": "resume_task", "task_id": "entry-task", "expected_version": version})
        frames = []
        for _ in range(40):
            f = ws.receive_json()
            frames.append(f)
            if f.get("type") == "error":
                break
        err = frames[-1]
        assert err == {**err, "type": "error", "code": "TASK_REVIEW_REQUIRED",
                       "message": "task_invalid_driver", "recoverable": True}, frames
        # the socket is still usable: an invalid resume gets its own normal error reply
        ws.send_json({"type": "resume_task", "task_id": "entry-task", "expected_version": 0})
        again = ws.receive_json()
        assert again.get("type") == "error" and again.get("code") == "INVALID_TASK_RESUME"
