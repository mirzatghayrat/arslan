"""INB5b (v0.1.64): a conversation lists its own stopped-job reminders.

The Inbox goes away (the INB5 board, approved 2026-10-31), and a stopped job's card comes back to its conversation. The window asks
for one conversation's reminders of one kind (`GET /proactive/items?conversation_id=&kind=`), whatever their status: a card set
aside or handled stays on its row with its state (Q7), so the conversation never reads the whole list.
"""
from server.db.models import ProactiveItem


async def _add(client, *rows):
    async with client.db_maker() as db:
        db.add_all(rows)
        await db.commit()


def _item(n, kind, conversation_id, status="new"):
    return ProactiveItem(id=n, kind=kind, fingerprint=f"fp:{n}", source_key=f"{kind}:{n}", title_key=f"title.{kind}",
                         evidence=[{"key": "x", "params": {}}], status=status, conversation_id=conversation_id)


async def _ids(client, query: str) -> list[int]:
    response = await client.get(f"/api/v1/proactive/items?{query}")
    assert response.status_code == 200, response.text
    return sorted(item["id"] for item in response.json()["items"])


async def test_a_conversation_lists_its_own_stopped_job_reminders_whatever_their_status(client):
    await _add(client, _item(1, "job_followup", "c1"), _item(2, "job_followup", "c1", status="dismissed"),
               _item(3, "job_followup", "c1", status="snoozed"), _item(4, "web_change", "c1"), _item(5, "job_followup", "c2"))
    assert await _ids(client, "scope=all&conversation_id=c1&kind=job_followup") == [1, 2, 3]


async def test_each_filter_narrows_its_scope_and_the_old_call_is_unchanged(client):
    await _add(client, _item(1, "job_followup", "c1"), _item(2, "job_followup", "c1", status="dismissed"),
               _item(4, "web_change", "c1"), _item(5, "job_followup", "c2"))
    assert await _ids(client, "scope=open&conversation_id=c1") == [1, 4]
    assert await _ids(client, "scope=open&kind=job_followup") == [1, 5]
    assert await _ids(client, "scope=open") == [1, 4, 5]


async def test_an_unknown_kind_or_an_overlong_conversation_id_is_refused(client):
    assert (await client.get("/api/v1/proactive/items?kind=bogus")).status_code == 422
    assert (await client.get("/api/v1/proactive/items?conversation_id=" + "x" * 101)).status_code == 422
