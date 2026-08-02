"""Gate item ⑦ — the server must be able to say WHICH conversations exist.

The defect this closes is not lost data, it is ORPHANED data. Messages persist
fine in `arslan_messages`, keyed by a `conversation_id` the FRONTEND mints
(`thread-${Date.now()}`, sessionPersistence.ts) and stores only in
localStorage. Every other conversation endpoint takes the id as a path
parameter, so localStorage was the single record of which conversations had
ever existed.

In the packaged app that record does not survive a restart:
`packaging/server_entry.py` asks the OS for an EPHEMERAL port each launch, the
window loads `http://127.0.0.1:<that port>`, and localStorage is partitioned by
ORIGIN — of which the port is part. Fresh partition, empty store, a brand-new
thread id, and the previous conversation unreachable forever.

Measured in the user's own packaged database before the fix: 10 conversations,
74 messages, five distinct thread ids created on a single day while the sidebar
showed one chat. The same code in dev accumulates 30-43 messages per
conversation, because a browser on a fixed port keeps its localStorage. That
difference in SHAPE is what distinguished "the history frame is broken" from
"the id is lost" — both hypotheses explain a blank screen equally well.

So: the server, which has always held the data, must also be able to enumerate
it. Pinning the port (also done) only protects future conversations; this is
what brings the existing ones back.
"""
from __future__ import annotations

from server.db.models import ArslanMessage


async def _seed(client, cid: str, n: int, *, first: str = "hello") -> None:
    async with client.db_maker() as db:
        for i in range(n):
            db.add(ArslanMessage(
                conversation_id=cid,
                role="user" if i == 0 else "arslan",
                content=first if i == 0 else f"reply {i}",
            ))
        await db.commit()


async def test_conversations_are_listed_without_knowing_their_ids(client):
    """The whole point: discovery. Every other endpoint needs the id up front."""
    await _seed(client, "thread-1", 3, first="chart the payment platforms")
    await _seed(client, "thread-2", 1, first="another one")

    r = await client.get("/api/v1/conversations")
    assert r.status_code == 200
    rows = r.json()
    assert {c["conversation_id"] for c in rows} == {"thread-1", "thread-2"}


async def test_each_row_carries_enough_to_render_a_sidebar_entry(client):
    await _seed(client, "thread-1", 3, first="chart the payment platforms")

    row = next(c for c in (await client.get("/api/v1/conversations")).json()
               if c["conversation_id"] == "thread-1")
    assert row["message_count"] == 3
    assert row["last_at"]
    # A recovered conversation has no title anywhere — localStorage was the only
    # place one ever lived. Deriving it from the opening message is what makes
    # the recovered entry identifiable instead of a row of ids.
    assert "chart the payment" in row["title"]


async def test_the_title_comes_from_the_users_own_words_not_the_reply(client):
    """Discriminating: taking `messages[0]` regardless of role would pass the
    test above whenever the user happens to speak first — which is usually, so
    the wrong implementation would look right."""
    async with client.db_maker() as db:
        db.add(ArslanMessage(conversation_id="t", role="arslan", content="Good morning."))
        db.add(ArslanMessage(conversation_id="t", role="user", content="restore my sessions"))
        await db.commit()

    row = (await client.get("/api/v1/conversations")).json()[0]
    assert "restore my sessions" in row["title"]
    assert "Good morning" not in row["title"]


async def test_most_recently_active_first(client):
    """The sidebar's order. Without it the list is a bag and the conversation
    the user was in the middle of is wherever the database happens to put it.

    🔴 The ids are chosen so ALPHABETICAL order CONTRADICTS recency. The first
    version named them "newer"/"older", and SQLite's GROUP BY returns groups in
    key order — "newer" < "older" — so the rows came back correctly sorted with
    no sort at all, and deleting the sort left this test green. A fixture whose
    natural order already agrees with the desired one cannot test ordering.
    """
    await _seed(client, "zzz-most-recent", 1)
    await _seed(client, "aaa-stale", 1)
    async with client.db_maker() as db:
        from sqlalchemy import select
        rows = (await db.execute(select(ArslanMessage))).scalars().all()
        for m in rows:
            if m.conversation_id == "zzz-most-recent":
                m.timestamp = m.timestamp.replace(year=m.timestamp.year + 1)
        await db.commit()

    listed = [c["conversation_id"] for c in (await client.get("/api/v1/conversations")).json()]
    assert listed == ["zzz-most-recent", "aaa-stale"], listed


async def test_an_empty_install_lists_nothing_rather_than_failing(client):
    r = await client.get("/api/v1/conversations")
    assert r.status_code == 200 and r.json() == []


async def test_a_deleted_conversation_stops_being_listed(client):
    """The list must agree with DELETE, or a deleted conversation comes back as
    a ghost sidebar row that opens onto nothing."""
    await _seed(client, "doomed", 2)
    assert (await client.delete("/api/v1/conversations/doomed")).status_code == 200
    assert (await client.get("/api/v1/conversations")).json() == []


async def test_the_listing_is_auth_gated_like_its_siblings(monkeypatch):
    """It enumerates the user's conversation titles — their own words. A listing
    endpoint outside the router's auth dependency would be a wider leak than any
    by-id endpoint, because it needs no id to be guessed.

    Uses the token-set idiom from test_brain_api rather than a `client_no_auth`
    fixture, which I assumed existed and does not."""
    import dataclasses

    from httpx import ASGITransport, AsyncClient

    from server import config

    monkeypatch.setattr(config, "settings",
                        dataclasses.replace(config.settings, api_token="secret-tok"))
    from server.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/conversations")
    assert r.status_code in (401, 403), r.status_code
