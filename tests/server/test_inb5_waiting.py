"""INB5 (v0.1.64): what is waiting on you, counted once (progress.waiting_on_user, the badge in GET /proactive/summary).

A unit is a conversation, a project or a scheduled task, never a row. A conversation waits when it has a card to approve, something
it could not ask while you were away that is newer than your last look at it (Q8, the user's 2026-10-31 approval of the INB5 board),
or an open "the job stopped" reminder. One in an active project counts as its project, and a task's own conversation counts as its
task. A scheduled task waits when its last run failed or it paused itself, has an open problem reminder, or one of its runs could not
ask something newer than your last look at the task (its own mark, scheduled_tasks.seen_at). A conversation the badge counts reads
"waiting" in the window's list, so every unit it counts has a marked row (#590 review F3).
"""
import time
from datetime import datetime, timedelta

import pytest

from server.db.companion_models import ConversationContext, Project
from sqlalchemy import select

from server.db.models import ApprovalEvent, ArslanMessage, ConversationSeen, ProactiveItem, ScheduledTask, ScheduledTaskRun
from server.services import approvals


async def _add(client, *rows):
    async with client.db_maker() as db:
        db.add_all(rows)
        await db.commit()


async def _waiting(client) -> dict:
    return (await client.get("/api/v1/proactive/summary")).json()["waiting"]


async def _window(client) -> dict[str, str]:
    return {row["conversation_id"]: row["state"] for row in (await client.get("/api/v1/conversations")).json()}


async def _phone(client) -> dict[str, str]:
    body = (await client.get("/api/v1/phone/conversations?limit=50")).json()
    return {row["id"]: row["state"] for row in body["conversations"]}


def _chat(cid):
    """A conversation that exists. A deleted one has no messages left, and the count skips it (#590 review F2)."""
    return [ArslanMessage(conversation_id=cid, role="user", content="hi"),
            ArslanMessage(conversation_id=cid, role="arslan", content="hello")]


def _refused(conversation_id, decided_by="away", hours_ago=1.0):
    return ApprovalEvent(created_at=datetime.utcnow() - timedelta(hours=hours_ago), conversation_id=conversation_id,
                         kind="send", target="mail:team", detail="send mail", mode="ask", decided_by=decided_by,
                         decision="expired" if decided_by == "away" else "deny")


def _item(n, kind, source_key, conversation_id=None, status="new"):
    return ProactiveItem(kind=kind, fingerprint=f"fp:{n}", source_key=source_key, title_key=f"title.{kind}",
                         evidence=[{"key": "x", "params": {}}], status=status, conversation_id=conversation_id)


def _task(id_, **over):
    fields = dict(id=id_, name=f"task {id_}", prompt="p", schedule_kind="interval", interval_s=3600, enabled=True,
                  consecutive_failures=0)
    fields.update(over)
    return ScheduledTask(**fields)


@pytest.fixture
def east_of_utc(monkeypatch):
    """Local time eight hours ahead of UTC. A window measured in local time would shrink from 24 hours to 16 (#590 review F5)."""
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


async def test_nothing_waits_on_an_empty_install(client):
    assert await _waiting(client) == {"count": 0, "conversations": [], "projects": [], "scheduled": []}


async def test_a_card_an_away_entry_and_a_stopped_job_each_make_their_conversation_wait_once(client, monkeypatch):
    monkeypatch.setattr(approvals, "all_pending", lambda: [{"call_id": "c1", "conversation_id": "chat-a"}])
    await _add(client, *_chat("chat-a"), *_chat("chat-b"), *_chat("chat-c"), *_chat("chat-d"),
               _refused("chat-a"), _refused("chat-b"),
               _item(1, "job_followup", "job:1", conversation_id="chat-a"),
               _item(2, "job_followup", "job:2", conversation_id="chat-c"),
               _item(3, "job_followup", "job:3", conversation_id="chat-d", status="snoozed"))   # set aside: not waiting
    waiting = await _waiting(client)
    assert waiting["conversations"] == ["chat-a", "chat-b", "chat-c"]                   # chat-a's three reasons count once
    assert waiting["count"] == 3


async def test_a_card_alone_makes_its_conversation_wait(client, monkeypatch):
    # A pending card is live by definition: it counts before the conversation has a stored message.
    monkeypatch.setattr(approvals, "all_pending", lambda: [{"call_id": "c9", "conversation_id": "chat-e"}])
    assert (await _waiting(client))["conversations"] == ["chat-e"]


async def test_an_away_entry_stops_waiting_once_you_open_its_conversation_and_stays_listed(client):
    await _add(client, *_chat("chat-a"), _refused("chat-a"))
    assert (await _waiting(client))["conversations"] == ["chat-a"]
    assert (await client.post("/api/v1/conversations/chat-a/seen")).status_code == 200
    assert (await _waiting(client))["count"] == 0
    listed = (await client.get("/api/v1/approvals/refused?hours=24&conversation_id=chat-a")).json()
    assert len(listed) == 1                                                              # still there until it expires
    await _add(client, _refused("chat-a", hours_ago=0))                                   # a newer one waits again
    assert (await _waiting(client))["conversations"] == ["chat-a"]


async def test_an_away_entry_older_than_a_day_has_expired(client):
    await _add(client, *_chat("chat-a"), _refused("chat-a", hours_ago=25))
    assert (await _waiting(client))["count"] == 0


async def test_an_away_entry_23_hours_old_still_counts_in_any_time_zone(client, east_of_utc):
    assert datetime.now() - datetime.utcnow() > timedelta(hours=7)                      # the fixture took: local is UTC+8
    await _add(client, *_chat("chat-a"), _refused("chat-a", hours_ago=23))
    assert (await _waiting(client))["conversations"] == ["chat-a"]


async def test_an_entry_from_the_moment_you_looked_counts_as_seen(client):
    await _add(client, *_chat("chat-a"))
    await client.post("/api/v1/conversations/chat-a/seen")
    async with client.db_maker() as db:
        at = await db.scalar(select(ConversationSeen.seen_at).where(ConversationSeen.conversation_id == "chat-a"))
    entry = _refused("chat-a")
    entry.created_at = at
    await _add(client, entry)
    assert (await _waiting(client))["count"] == 0


async def test_a_deleted_conversation_stops_counting(client, monkeypatch):
    """#590 review F2: deleting a conversation keeps its ledger rows and reminders; neither counts once it is gone."""
    await _add(client, *_chat("gone"), _refused("gone"), _item(1, "job_followup", "job:1", conversation_id="gone"),
               _item(2, "job_followup", "job:2", conversation_id="never"))               # no conversation by that id
    assert (await _waiting(client))["conversations"] == ["gone"]
    assert (await client.delete("/api/v1/conversations/gone")).status_code == 200
    assert (await _waiting(client))["count"] == 0


async def test_only_a_stopped_job_reminder_makes_a_conversation_wait(client):
    await _add(client, *_chat("chat-w"), *_chat("chat-j"),
               _item(1, "web_change", "web:1", conversation_id="chat-w"),
               _item(2, "job_followup", "job:2", conversation_id="chat-j"))
    assert (await _waiting(client))["conversations"] == ["chat-j"]


async def test_a_conversation_the_badge_counts_reads_waiting_in_the_window_and_unchanged_on_phones(client):
    """#590 review F3a: every conversation the badge counts has a marked row. Phones keep today's values until INB4's phone half."""
    await _add(client, *_chat("chat-a"), *_chat("chat-b"), _refused("chat-a"))
    assert (await _window(client))["chat-a"] == "waiting"
    assert (await _phone(client))["chat-a"] == "idle"
    await client.post("/api/v1/conversations/chat-a/seen")
    assert (await _window(client))["chat-a"] == "idle"
    assert (await _window(client))["chat-b"] == "done_unseen"                           # not counted: its own state


async def test_conversations_in_a_project_count_as_the_project(client):
    await _add(client, Project(id="p1", name="Home"))
    await _add(client, ConversationContext(id="chat-a", project_id="p1"), ConversationContext(id="chat-b", project_id="p1"),
               *_chat("chat-a"), *_chat("chat-b"), *_chat("chat-c"),
               _refused("chat-a"), _refused("chat-b"), _refused("chat-c"))
    waiting = await _waiting(client)
    assert (waiting["projects"], waiting["conversations"], waiting["count"]) == (["p1"], ["chat-c"], 2)


async def test_conversations_in_an_archived_project_count_one_by_one(client):
    """#590 review F3c: an archived project has no row in the sidebar; its conversations are listed under 「最近」."""
    await _add(client, Project(id="p1", name="Old", status="archived"))
    await _add(client, ConversationContext(id="chat-a", project_id="p1"), ConversationContext(id="chat-b", project_id="p1"),
               *_chat("chat-a"), *_chat("chat-b"), _refused("chat-a"), _refused("chat-b"))
    waiting = await _waiting(client)
    assert (waiting["projects"], waiting["conversations"], waiting["count"]) == ([], ["chat-a", "chat-b"], 2)


async def test_a_scheduled_task_waits_when_it_failed_paused_itself_has_a_problem_or_could_not_ask(client):
    await _add(client, _task(1), _task(2, enabled=False, paused_reason="3 failures"), _task(3), _task(4),
               _task(5, enabled=False), _task(6, conversation_id="chat-x"))
    await _add(client, ScheduledTaskRun(task_id=1, outcome="error"), ScheduledTaskRun(task_id=4, outcome="ok"),
               _item(7, "scheduled_problem", "sched:3"),
               _refused("chat-x", decided_by="policy"), _refused("scheduled-4", decided_by="policy", hours_ago=100))
    waiting = await _waiting(client)
    assert waiting["scheduled"] == [1, 2, 3, 4, 6]       # 5 is paused by hand; 4's entry is four days old, inside a week
    assert waiting["conversations"] == []                # a scheduled run's entry belongs to its task, not its conversation


async def test_only_the_last_run_counts(client):
    await _add(client, _task(1), _task(2))
    await _add(client, ScheduledTaskRun(task_id=1, outcome="error"), ScheduledTaskRun(task_id=2, outcome="ok"))
    await _add(client, ScheduledTaskRun(task_id=1, outcome="ok"), ScheduledTaskRun(task_id=2, outcome="error"))
    assert (await _waiting(client))["scheduled"] == [2]  # 1 failed once and has worked since


async def test_a_problem_reminder_counts_only_while_open(client):
    await _add(client, _task(3), _task(5), _task(8))
    await _add(client, _item(1, "scheduled_problem", "sched:3", status="dismissed"),
               _item(2, "scheduled_problem", "sched:5", status="accepted"), _item(3, "scheduled_problem", "sched:8", status="seen"))
    assert (await _waiting(client))["scheduled"] == [8]


async def test_a_scheduled_task_stops_waiting_for_its_entries_once_you_open_it(client):
    await _add(client, _task(4), *_chat("scheduled-4"))
    await _add(client, _refused("scheduled-4", decided_by="policy"))
    assert (await _waiting(client))["scheduled"] == [4]
    assert (await client.post("/api/v1/conversations/scheduled-4/seen")).status_code == 200
    assert (await _waiting(client))["scheduled"] == [4]  # the task's mark is its own, not its conversation's
    assert (await client.post("/api/v1/scheduled-tasks/4/seen")).status_code == 200
    assert (await _waiting(client))["scheduled"] == []
    await _add(client, _refused("scheduled-4", decided_by="policy", hours_ago=0))
    assert (await _waiting(client))["scheduled"] == [4]  # a newer one waits again


async def test_an_entry_from_the_moment_you_opened_the_task_counts_as_seen(client):
    await _add(client, _task(4))
    await client.post("/api/v1/scheduled-tasks/4/seen")
    async with client.db_maker() as db:
        at = (await db.get(ScheduledTask, 4)).seen_at
    entry = _refused("scheduled-4", decided_by="policy")
    entry.created_at = at
    await _add(client, entry)
    assert (await _waiting(client))["scheduled"] == []


async def test_a_task_that_writes_into_a_chat_keeps_its_own_mark(client):
    await _add(client, _task(6, conversation_id="chat-x"), *_chat("chat-x"))
    await _add(client, _refused("chat-x", decided_by="policy"))
    await client.post("/api/v1/conversations/chat-x/seen")
    assert (await _waiting(client))["scheduled"] == [6]
    await client.post("/api/v1/scheduled-tasks/6/seen")
    assert (await _waiting(client))["scheduled"] == []


async def test_marking_a_task_that_does_not_exist_is_refused(client):
    response = await client.post("/api/v1/scheduled-tasks/99/seen")
    assert (response.status_code, response.json()["detail"]["code"]) == (404, "scheduled.task_not_found")


async def test_a_tasks_own_conversation_counts_as_its_task(client, monkeypatch):
    """#590 review F4: the task's own conversation (scheduled-<id>) and the task are one thing, counted once."""
    monkeypatch.setattr(approvals, "all_pending", lambda: [{"call_id": "c1", "conversation_id": "scheduled-4"},
                                                           {"call_id": "c2", "conversation_id": "scheduled-7"},
                                                           {"call_id": "c3", "conversation_id": "scheduled-99"}])
    await _add(client, _task(4), _task(7))
    await _add(client, ScheduledTaskRun(task_id=4, outcome="error"))
    waiting = await _waiting(client)
    assert (waiting["scheduled"], waiting["conversations"], waiting["count"]) == ([4, 7], ["scheduled-99"], 3)  # 99: no task


def test_migration_0084_adds_the_tasks_seen_column_once(tmp_path):
    """An upgrade adds `scheduled_tasks.seen_at`; running it again, or on a database without the table, changes nothing."""
    import sqlalchemy as sa

    from server.db.migrations.versions._0084_scheduled_task_seen import upgrade_sync
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'before.db'}")
    with engine.begin() as connection:
        upgrade_sync(connection)                                                        # no table yet: nothing to do
        connection.exec_driver_sql("CREATE TABLE scheduled_tasks (id INTEGER PRIMARY KEY, name VARCHAR(80))")
        upgrade_sync(connection)
        upgrade_sync(connection)
        columns = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(scheduled_tasks)")]
    engine.dispose()
    assert columns.count("seen_at") == 1
