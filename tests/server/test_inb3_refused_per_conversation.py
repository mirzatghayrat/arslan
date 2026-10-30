"""INB3, the server half (docs/plans/0164/INB-inbox-progress.md): what could not be asked, per conversation. The
scheduled tasks' page, and later each conversation, list only their own refusals. The filter runs before the
grouping: grouped first, two conversations that refused the same thing made one group whose newest row named
only one of them, so the other conversation saw nothing."""
from datetime import datetime, timedelta

import pytest

from server.db.models import ApprovalEvent
from server.services import permission_store


def _row(conversation_id, minutes_ago, *, decided_by="policy", decision="deny"):
    return ApprovalEvent(created_at=datetime.utcnow() - timedelta(minutes=minutes_ago), conversation_id=conversation_id,
                         kind="command", target="curl example.com", mode="ask", decided_by=decided_by,
                         decision=decision)


async def _seed(client, rows):
    async with client.db_maker() as db:
        db.add_all(rows)
        await db.commit()


async def test_each_conversation_sees_its_own_refusal_of_the_same_thing(client):
    await _seed(client, [_row("scheduled-1", 30), _row("scheduled-2", 10)])     # the same command, refused in two
    since = datetime.utcnow() - timedelta(hours=1)
    async with client.db_maker() as db:
        everywhere = await permission_store.refused_groups(db, since)
        first = await permission_store.refused_groups(db, since, conversation_id="scheduled-1")
        second = await permission_store.refused_groups(db, since, conversation_id="scheduled-2")
    assert [(row.conversation_id, count) for row, count, _ in everywhere] == [("scheduled-2", 2)]   # as today
    assert [(row.conversation_id, count) for row, count, _ in first] == [("scheduled-1", 1)]
    assert [(row.conversation_id, count) for row, count, _ in second] == [("scheduled-2", 1)]


async def test_the_list_takes_a_conversation(client):
    await _seed(client, [_row("scheduled-1", 30), _row("scheduled-2", 10),
                         _row("c-chat", 5, decided_by="away", decision="expired")])
    mine = (await client.get("/api/v1/approvals/refused", params={"conversation_id": "scheduled-1"})).json()
    assert [(e["conversation_id"], e["count"], e["unattended"]) for e in mine] == [("scheduled-1", 1, True)]
    chat = (await client.get("/api/v1/approvals/refused", params={"conversation_id": "c-chat"})).json()
    assert [(e["conversation_id"], e["unattended"]) for e in chat] == [("c-chat", False)]
    everything = (await client.get("/api/v1/approvals/refused")).json()
    assert sorted(e["conversation_id"] for e in everything) == ["c-chat", "scheduled-2"]      # grouped as today


@pytest.mark.parametrize("bad", ["", "x" * 101], ids=["empty", "too-long"])
async def test_a_conversation_id_that_names_none_is_refused(client, bad):
    got = await client.get("/api/v1/approvals/refused", params={"conversation_id": bad})
    assert got.status_code == 422
