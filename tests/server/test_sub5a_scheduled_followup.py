"""SUB5a follow-up to #799: a scheduled task paused because its conversation was deleted says so everywhere, and stays
paused.

#799 pauses such a task (`paused_reason="conversation_deleted"`) and gives every new task a conversation of its own
(`scheduled-<uuid>`). What this pins, through the real scheduler tick, the heartbeat's sync, the create route and the
Inbox:
- the Mac's event for this pause names the task and its reason, and no conversation (so a click never opens the
  deleted one), and the Inbox's reminder words the reason instead of "failed 0 times" and the bare code;
- the heartbeat's sync, run at every settings save and every boot, never turns such a task on again; turning the
  heartbeat off and on carries on in its conversation, or a new one when that one was deleted;
- "make it again" (the old task's id, reused by SQLite) starts with none of the old task's reminders.
"""
from datetime import datetime, timedelta

from sqlalchemy import select

from arslan.proactive_policy import ProactiveConfig
from server.db.companion_models import ConversationContext
from server.db.models import ArslanMessage, ProactiveItem, ProactiveMute, ScheduledTask, Setting
from server.services import desktop_status, heartbeat, proactive_detectors, proactive_service, scheduler, sub_sessions
from tests.server.test_s64_0_outside_content_gaps import memory  # noqa: F401  (the fixture)
from tests.server.test_sub4_report import runs  # noqa: F401  (the fixture)
from tests.server.test_sub5a_lifecycle import _fired, _fresh, _runs_of, _said, _scheduled_turns, client  # noqa: F401

BODY = {"name": "daily", "prompt": "Sum up the day", "schedule_kind": "interval", "interval_s": 3600}


def _paused_events(after: int, task_id: int) -> list[dict]:
    return [{key: event.get(key) for key in ("conversation_id", "task_id", "reason")}
            for event in desktop_status.snapshot(after)["events"]
            if event["kind"] == "scheduled_paused" and event["task_id"] == task_id]


async def _delete_conversation(http, db, cid) -> None:
    """The user deletes the task's conversation, and the process restarts: only its tombstone refuses from then on."""
    async with db() as session:
        session.add(ArslanMessage(conversation_id=cid, role="arslan", content="yesterday's summary"))
        await session.commit()
    assert (await http.delete(f"/api/v1/conversations/{cid}")).status_code == 200
    sub_sessions._deleted.clear()


async def _ticks(n: int = 1) -> None:
    try:
        for _ in range(n):
            await scheduler.tick()
            await _fired()
    finally:
        scheduler._tasks.clear()


async def _due_now(db, task_id: int) -> None:
    async with db() as session:
        (await session.get(ScheduledTask, task_id)).next_due_at = datetime.utcnow() - timedelta(minutes=1)
        await session.commit()


async def _inbox(http) -> list[dict]:
    """The scan the Inbox runs, for schedule problems, then what it lists."""
    found = await proactive_detectors.scheduled_problems(
        proactive_detectors.Context(now=datetime.utcnow(), config=ProactiveConfig()))
    await proactive_service.ingest(found, now_utc=datetime.utcnow())
    return (await http.get("/api/v1/proactive/items")).json()["items"]


async def test_the_pause_tells_the_mac_why_names_no_conversation_and_the_inbox_words_it(
        runs, client, monkeypatch):  # noqa: F811
    _scheduled_turns(monkeypatch)
    task = (await client.post("/api/v1/scheduled-tasks", json=BODY)).json()
    await _delete_conversation(client, runs, task["conversation_id"])
    await _due_now(runs, task["id"])
    after = desktop_status.snapshot()["cursor"]
    await _ticks(3)
    assert await _runs_of(runs, task["id"]) == [("error", "conversation_deleted")]
    # One event, with the reason the Mac words and the task it opens; no conversation, so nothing opens the deleted one.
    assert _paused_events(after, task["id"]) == [
        {"conversation_id": None, "task_id": task["id"], "reason": "conversation_deleted"}]
    [item] = [item for item in await _inbox(client) if item["source_key"] == f"sched:{task['id']}"]
    assert item["evidence"] == [{"key": "sched.state", "params": {
        "name": "daily", "failures": 0, "paused": True, "reason": "conversation_deleted"}}]


async def test_a_reminder_still_quotes_the_failures_before_the_delete(runs, client, monkeypatch):  # noqa: F811
    """Only the run that says "conversation deleted" is left out: real failures before it are still quoted."""
    from server.db.models import ScheduledTaskRun
    _scheduled_turns(monkeypatch)
    task = (await client.post("/api/v1/scheduled-tasks", json=BODY)).json()
    async with runs() as session:
        session.add(ScheduledTaskRun(task_id=task["id"], outcome="error", reason="provider timeout",
                                     started_at=datetime.utcnow()))
        await session.commit()
    await _delete_conversation(client, runs, task["conversation_id"])
    await _due_now(runs, task["id"])
    await _ticks()
    [item] = [item for item in await _inbox(client) if item["source_key"] == f"sched:{task['id']}"]
    assert [(line["key"], line.get("quote")) for line in item["evidence"]] == [
        ("sched.state", None), ("sched.run", "provider timeout")]


async def _turn_heartbeat(db, on: bool) -> None:
    """A settings save (PUT /settings ends with this sync, and so does every boot)."""
    async with db() as session:
        for key, value in (("heartbeat_enabled", "true" if on else "false"), ("heartbeat_checklist", "- watch CI")):
            row = await session.get(Setting, key)
            if row is None:
                session.add(Setting(key=key, value=value))
            else:
                row.value = value
        await session.commit()
    await heartbeat.sync_task()


async def _heartbeat(db) -> ScheduledTask | None:
    async with db() as session:
        return (await session.scalars(select(ScheduledTask).where(ScheduledTask.name == heartbeat.TASK_NAME))).first()


async def test_the_heartbeats_sync_never_turns_a_task_on_whose_conversation_was_deleted(
        runs, client, monkeypatch):  # noqa: F811
    ran = _scheduled_turns(monkeypatch)
    await _turn_heartbeat(runs, True)
    first = await _heartbeat(runs)
    await _delete_conversation(client, runs, first.conversation_id)
    await _due_now(runs, first.id)
    await _ticks()
    assert await _runs_of(runs, first.id) == [("error", "conversation_deleted")]
    after = desktop_status.snapshot()["cursor"]
    for _ in range(2):                                          # two saves (or boots), each followed by a due tick
        await _turn_heartbeat(runs, True)
        task = await _heartbeat(runs)
        assert (task.id, task.enabled, task.paused_reason, task.next_due_at) == (
            first.id, False, "conversation_deleted", None)
        await _ticks()
    assert await _runs_of(runs, first.id) == [("error", "conversation_deleted")]
    assert _paused_events(after, first.id) == [] and ran == []
    # Off and on makes it again, in a conversation no tombstone holds, and it runs there.
    await _turn_heartbeat(runs, False)
    await _turn_heartbeat(runs, True)
    again = await _heartbeat(runs)
    assert again.enabled and again.paused_reason is None
    assert again.conversation_id.startswith("scheduled-") and again.conversation_id != first.conversation_id
    await _due_now(runs, again.id)
    await _ticks()
    assert ran == [again.conversation_id]


async def test_turning_the_heartbeat_off_and_on_carries_on_in_its_conversation(runs, client, monkeypatch):  # noqa: F811
    ran = _scheduled_turns(monkeypatch)
    await _turn_heartbeat(runs, True)
    first = (await _heartbeat(runs)).conversation_id
    async with runs() as session:
        session.add(ArslanMessage(conversation_id=first, role="arslan", content="nothing needs doing"))
        await session.commit()
    for _ in range(2):
        await _turn_heartbeat(runs, False)
        assert await _heartbeat(runs) is None
        await _turn_heartbeat(runs, True)
        assert (await _heartbeat(runs)).conversation_id == first
    task = await _heartbeat(runs)
    await _due_now(runs, task.id)
    await _ticks()
    assert ran == [first] and await _said(runs, first) == [("nothing needs doing", None)]


async def test_a_heartbeat_off_while_its_conversation_is_deleted_comes_back_in_a_new_one(
        runs, client, monkeypatch):  # noqa: F811
    """Deleted while the heartbeat is off: the kept id is a tombstone now, never reused. Also in the process that
    deleted it, before its tombstone could be read after a restart (the delete's own mark)."""
    _scheduled_turns(monkeypatch)
    await _turn_heartbeat(runs, True)
    first = (await _heartbeat(runs)).conversation_id
    await _turn_heartbeat(runs, False)
    await _delete_conversation(client, runs, first)
    await _turn_heartbeat(runs, True)
    second = (await _heartbeat(runs)).conversation_id
    assert second != first
    await _turn_heartbeat(runs, False)
    sub_sessions._deleted.add(second)                            # its delete began in this process
    await _turn_heartbeat(runs, True)
    assert (await _heartbeat(runs)).conversation_id not in (first, second)


async def test_making_a_task_again_starts_without_the_old_tasks_reminders(runs, client, monkeypatch):  # noqa: F811
    """The page tells the user to make the task again. The new one gets the old one's id from SQLite, and with it, on
    main, the old task's open reminder, which counted the new, healthy task as waiting."""
    _scheduled_turns(monkeypatch)
    first = (await client.post("/api/v1/scheduled-tasks", json=BODY)).json()
    await _delete_conversation(client, runs, first["conversation_id"])
    await _due_now(runs, first["id"])
    await _ticks()
    key = f"sched:{first['id']}"
    assert [item["source_key"] for item in await _inbox(client)] == [key]
    async with runs() as session:
        session.add(ProactiveMute(key=key))                    # an older "stop this source" of the old task
        await session.commit()
    assert first["id"] in (await client.get("/api/v1/proactive/summary")).json()["waiting"]["scheduled"]
    assert (await client.delete(f"/api/v1/scheduled-tasks/{first['id']}")).status_code == 200
    again = (await client.post("/api/v1/scheduled-tasks", json=BODY)).json()
    assert again["id"] == first["id"]                           # the reuse
    async with runs() as session:
        assert (await session.scalars(select(ProactiveItem).where(ProactiveItem.source_key == key))).all() == []
        assert await session.get(ProactiveMute, key) is None
    assert (await client.get("/api/v1/proactive/summary")).json()["waiting"]["scheduled"] == []
    # The new task's own problem is raised, not held back by the old one's fingerprint.
    await _delete_conversation(client, runs, again["conversation_id"])
    await _due_now(runs, again["id"])
    await _ticks()
    assert [item["source_key"] for item in await _inbox(client)] == [key]


async def _old_task_left(db, task_id: int) -> None:
    """A task that paused on a deleted conversation and was deleted, leaving its reminder and a mute behind."""
    async with db() as session:
        session.add(ScheduledTask(id=task_id, name="old", prompt="p", schedule_kind="interval", interval_s=3600,
                                  enabled=False, consecutive_failures=0, paused_reason="conversation_deleted"))
        await session.commit()
        session.add_all([ProactiveItem(kind="scheduled_problem", fingerprint=f"fp:old:{task_id}",
                                       source_key=f"sched:{task_id}", title_key="title.scheduled_problem", evidence=[]),
                         ProactiveMute(key=f"sched:{task_id}")])
        await session.delete(await session.get(ScheduledTask, task_id))
        await session.commit()


async def _left_of(db, task_id: int) -> tuple[list, object]:
    async with db() as session:
        return ((await session.scalars(select(ProactiveItem.id).where(ProactiveItem.source_key == f"sched:{task_id}"))).all(),
                await session.get(ProactiveMute, f"sched:{task_id}"))


async def test_the_schedule_tool_and_the_heartbeat_start_without_the_old_tasks_reminders(runs):  # noqa: F811
    from server.registry import schedule_tools
    await _old_task_left(runs, 1)
    made = await schedule_tools.ScheduleTaskExecutor().execute({"name": "again", "prompt": "p", "when": "every: 3600"})
    assert made["ok"] and made["task_id"] == 1
    assert await _left_of(runs, 1) == ([], None)
    await _old_task_left(runs, 2)
    await _turn_heartbeat(runs, True)
    assert (await _heartbeat(runs)).id == 2 and await _left_of(runs, 2) == ([], None)


async def test_the_heartbeats_conversation_is_kept_in_no_setting_the_user_sees(runs):  # noqa: F811
    from server.services import settings_service
    assert heartbeat.CONVERSATION_KEY not in settings_service._PLAIN_KEYS + settings_service._INT_KEYS
    await _turn_heartbeat(runs, True)
    async with runs() as session:
        assert heartbeat.CONVERSATION_KEY not in await settings_service.get_settings(session)
        assert (await session.get(Setting, heartbeat.CONVERSATION_KEY)).value == (await _heartbeat(runs)).conversation_id
        row = await session.get(ConversationContext, (await _heartbeat(runs)).conversation_id)
    assert row is None                                          # the sync reads the context row, never makes one
