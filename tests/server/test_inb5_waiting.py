"""INB5 (v0.1.64): what is waiting on you, counted once (progress.waiting_on_user, the badge in GET /proactive/summary).

A unit is a conversation, a project or a scheduled task, never a row. A conversation waits when it has a card to approve, something
it could not ask while you were away that is newer than your last look at it (Q8, the user's 2026-10-31 approval of the INB5 board),
or an open "the job stopped" reminder; one in a project counts as its project. A scheduled task waits when it failed or paused
itself, has an open problem reminder, or one of its runs could not ask something newer than your last look at it.
"""
from datetime import datetime, timedelta

from server.db.companion_models import ConversationContext, Project
from server.db.models import ApprovalEvent, ProactiveItem, ScheduledTask, ScheduledTaskRun
from server.services import approvals


async def _add(client, *rows):
    async with client.db_maker() as db:
        db.add_all(rows)
        await db.commit()


async def _waiting(client) -> dict:
    return (await client.get("/api/v1/proactive/summary")).json()["waiting"]


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


async def test_nothing_waits_on_an_empty_install(client):
    assert await _waiting(client) == {"count": 0, "conversations": [], "projects": [], "scheduled": []}


async def test_a_card_an_away_entry_and_a_stopped_job_each_make_their_conversation_wait_once(client, monkeypatch):
    monkeypatch.setattr(approvals, "all_pending", lambda: [{"call_id": "c1", "conversation_id": "chat-a"}])
    await _add(client, _refused("chat-a"), _refused("chat-b"),
               _item(1, "job_followup", "job:1", conversation_id="chat-a"),
               _item(2, "job_followup", "job:2", conversation_id="chat-c"),
               _item(3, "job_followup", "job:3", conversation_id="chat-d", status="snoozed"))   # set aside: not waiting
    waiting = await _waiting(client)
    assert waiting["conversations"] == ["chat-a", "chat-b", "chat-c"]                   # chat-a's three reasons count once
    assert waiting["count"] == 3


async def test_a_card_alone_makes_its_conversation_wait(client, monkeypatch):
    monkeypatch.setattr(approvals, "all_pending", lambda: [{"call_id": "c9", "conversation_id": "chat-e"}])
    assert (await _waiting(client))["conversations"] == ["chat-e"]


async def test_an_away_entry_stops_waiting_once_you_open_its_conversation_and_stays_listed(client):
    await _add(client, _refused("chat-a"))
    assert (await _waiting(client))["conversations"] == ["chat-a"]
    assert (await client.post("/api/v1/conversations/chat-a/seen")).status_code == 200
    assert (await _waiting(client))["count"] == 0
    listed = (await client.get("/api/v1/approvals/refused?hours=24&conversation_id=chat-a")).json()
    assert len(listed) == 1                                                              # still there until it expires
    await _add(client, _refused("chat-a", hours_ago=0))                                   # a newer one waits again
    assert (await _waiting(client))["conversations"] == ["chat-a"]


async def test_an_away_entry_older_than_a_day_has_expired(client):
    await _add(client, _refused("chat-a", hours_ago=25))
    assert (await _waiting(client))["count"] == 0


async def test_conversations_in_a_project_count_as_the_project(client, monkeypatch):
    await _add(client, Project(id="p1", name="Home"))
    await _add(client, ConversationContext(id="chat-a", project_id="p1"), ConversationContext(id="chat-b", project_id="p1"),
               _refused("chat-a"), _refused("chat-b"), _refused("chat-c"))
    waiting = await _waiting(client)
    assert (waiting["projects"], waiting["conversations"], waiting["count"]) == (["p1"], ["chat-c"], 2)


async def test_a_scheduled_task_waits_when_it_failed_paused_itself_has_a_problem_or_could_not_ask(client):
    await _add(client, _task(1), _task(2, enabled=False, paused_reason="3 failures"), _task(3), _task(4),
               _task(5, enabled=False), _task(6, conversation_id="chat-x"))
    await _add(client, ScheduledTaskRun(task_id=1, outcome="error"), ScheduledTaskRun(task_id=4, outcome="ok"),
               _item(7, "scheduled_problem", "sched:3"),
               _refused("chat-x", decided_by="policy"), _refused("scheduled-4", decided_by="policy", hours_ago=100))
    waiting = await _waiting(client)
    assert waiting["scheduled"] == [1, 2, 3, 4, 6]       # 5 is paused by hand; 4's entry is four days old, inside a week
    assert waiting["conversations"] == []                # a scheduled run's entry belongs to its task, not its conversation


async def test_a_scheduled_task_stops_waiting_for_its_entries_once_you_open_it(client):
    await _add(client, _task(4))
    await _add(client, _refused("scheduled-4", decided_by="policy"))
    assert (await _waiting(client))["scheduled"] == [4]
    await client.post("/api/v1/conversations/scheduled-4/seen")
    assert (await _waiting(client))["scheduled"] == []
