"""INB7 (v0.1.64): a job a restart cut short says so when it happens.

The boot pass closed such a job with the user's own cancel, so its record read "user_cancelled" and its conversation read idle. It
now records "process_interrupted" at the time (the INB card: a reason written when it happens, never worked out later from the
messages), and the window reads the conversation as unfinished. Phones keep today's value until INB4's phone half: the Bridge
frame's values wait on the user.
"""
from unittest.mock import AsyncMock

from server.db.models import ArslanMessage, CompanionTask
from server.services import background_jobs, runtime_messages


async def _add(client, *rows):
    async with client.db_maker() as db:
        db.add_all(rows)
        await db.commit()


async def test_a_job_a_restart_cut_short_is_recorded_as_interrupted_and_your_own_cancel_stays_yours(execution_db, monkeypatch):
    from server.services.task_repository import repository
    from tests.server.test_task_repository import spec
    monkeypatch.setattr(runtime_messages, "selected_locale", AsyncMock(return_value="en"))
    async with repository() as repo:
        for identity in ("job-cut", "job-mine"):
            created = await repo.create(spec(identity, instruction=f"Goal of {identity}"), f"conv-{identity}",
                                        privacy={"driver": {"kind": "background"}})
            await repo.start(identity, created["version"])
        await repo.cancel("job-mine")                          # the user stops this one before the restart
    async with repository() as repo:
        await repo.recover_interrupted()                       # what a restart finds
    assert await background_jobs.report_interrupted() == 1
    async with execution_db() as db:
        cut = await db.get(CompanionTask, "job-cut")
        mine = await db.get(CompanionTask, "job-mine")
    assert (cut.phase, cut.pause_reason) == ("cancelled", "process_interrupted")
    assert (mine.phase, mine.pause_reason) == ("cancelled", "user_cancelled")


async def test_the_window_reads_an_interrupted_jobs_conversation_unfinished_and_phones_keep_todays_value(client):
    await _add(client, ArslanMessage(conversation_id="task-cut", role="user", content="tidy my notes"),
               ArslanMessage(conversation_id="task-cut", role="arslan", content="a restart cut this short", job_outcome="interrupted"))
    window = {row["conversation_id"]: row["state"] for row in (await client.get("/api/v1/conversations")).json()}
    phone = {row["id"]: row["state"] for row in (await client.get("/api/v1/phone/conversations?limit=50")).json()["conversations"]}
    assert (window["task-cut"], phone["task-cut"]) == ("unfinished", "idle")


async def test_a_new_turn_in_that_conversation_reads_working_not_unfinished(client, monkeypatch):
    from server.services import run_registry
    await _add(client, ArslanMessage(conversation_id="task-cut", role="user", content="tidy my notes"),
               ArslanMessage(conversation_id="task-cut", role="arslan", content="a restart cut this short", job_outcome="interrupted"))
    monkeypatch.setattr(run_registry, "active_for", lambda cid: cid == "task-cut")
    window = {row["conversation_id"]: row["state"] for row in (await client.get("/api/v1/conversations")).json()}
    assert window["task-cut"] == "working"
