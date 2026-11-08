"""The read the Bridge makes before it links a conversation a phone frame names (chat.send, task.stop): its history
with `limit=1` (desktop/bridge, ConversationLinks.linkNamed). A sub-session is `not_found` there, so the Bridge never
opens its `/ws/arslan/<id>` socket for a phone (SUB3's open end, #767). An ordinary conversation, or one the Mac has
nothing stored for yet, answers, and links as before. The Bridge's own tests (QuickAskTests) cover what it does with
each answer."""
from __future__ import annotations

from server.db.models import ArslanMessage
from server.services import sub_sessions

ROOT = "c-parent"


def probe(conversation_id: str) -> str:
    return f"/api/v1/phone/conversations/{conversation_id}/history?limit=1"


async def test_the_bridges_link_read_refuses_a_sub_session_and_answers_for_any_other(client, monkeypatch):
    from server.db import session as db_session
    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    async with client.db_maker() as db:
        await sub_sessions.create_child(db, ROOT, "sub-kid")
        await db.commit()
        await sub_sessions.create_child(db, "sub-kid", "sub-grandkid")
        await db.commit()
        for cid in (ROOT, "sub-kid", "sub-grandkid"):
            db.add(ArslanMessage(conversation_id=cid, role="user", content=f"words of {cid}"))
        await db.commit()
    for cid in ("sub-kid", "sub-grandkid"):
        got = await client.get(probe(cid))
        assert (got.status_code, got.json()["detail"]) == (404, "not_found"), cid
    parent = await client.get(probe(ROOT))
    assert parent.status_code == 200
    assert [m["text"] for m in parent.json()["messages"]] == [f"words of {ROOT}"]
    unknown = await client.get(probe("c-nothing-stored"))
    assert (unknown.status_code, unknown.json()["messages"]) == (200, [])
