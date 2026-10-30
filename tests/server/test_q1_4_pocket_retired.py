"""Q1 card, #4 (the user, 2026-10-29: "Keep as a conversation"): the pocket, the one conversation every phone shared
before §5.8 ("Remote"), is retired. On the Mac its old messages stay as an ordinary conversation, named after its
first message, not pinned and not called Remote; the window can read, continue or delete it. Phones never see it:
the Bridge refuses every frame that names it and never links it (desktop/bridge, PocketRetiredTests)."""
from datetime import datetime

from server.db.models import ArslanMessage


async def test_the_pocket_is_an_ordinary_conversation_on_the_mac_with_its_messages(client):
    async with client.db_maker() as db:
        for i, (cid, role, text, at) in enumerate([
            ("pocket", "user", "what's on today?", "2026-10-20T08:00:00"),
            ("pocket", "arslan", "Two meetings.", "2026-10-20T08:00:05"),
            ("trip", "user", "Plan a trip to Acme City", "2026-10-21T09:00:00"),
        ], start=1):
            db.add(ArslanMessage(id=i, conversation_id=cid, role=role, content=text, timestamp=datetime.fromisoformat(at)))
        await db.commit()
    listed = (await client.get("/api/v1/conversations")).json()
    assert [(c["conversation_id"], c["title"], c["kind"]) for c in listed] == [
        ("trip", "Plan a trip to Acme City", "chat"), ("pocket", "what's on today?", "chat")]       # newest first
    history = (await client.get("/api/v1/phone/conversations/pocket/history")).json()["messages"]
    assert [m["text"] for m in history] == ["what's on today?", "Two meetings."]                   # nothing moved
    assert (await client.delete("/api/v1/conversations/pocket")).status_code == 200                # the window may delete it
    assert [c["conversation_id"] for c in (await client.get("/api/v1/conversations")).json()] == ["trip"]


async def test_the_phones_list_leaves_the_pocket_out_before_it_pages(client):
    """#525 review, F2: dropped after the page was cut, a page of one could come back empty with has_more true,
    which stops a phone's pager. The phone list leaves the pocket out first."""
    async with client.db_maker() as db:
        for i, (cid, at) in enumerate([("trip", "2026-10-20T08:00:00"), ("pocket", "2026-10-21T08:00:00"),
                                       ("plan", "2026-10-19T08:00:00")], start=1):
            db.add(ArslanMessage(id=i, conversation_id=cid, role="user", content=cid, timestamp=datetime.fromisoformat(at)))
        await db.commit()
    first = (await client.get("/api/v1/phone/conversations?limit=1")).json()
    assert ([c["id"] for c in first["conversations"]], first["has_more"]) == (["trip"], True)
    rest = (await client.get("/api/v1/phone/conversations",
                             params={"limit": 5, "before": first["conversations"][0]["updated_at"]})).json()
    assert ([c["id"] for c in rest["conversations"]], rest["has_more"]) == (["plan"], False)
