"""The sidebar's search, its "In messages" part: GET /conversations/search (v0.1.64, the approved mock).

- It needs the access token, like every route on the conversations router.
- It returns only conversations the window lists: a quick question never shows here.
- Temporary and no-memory conversations, and sub-sessions, are never found by their messages (a sub-session is
  found by its title only, in the window).
- The snippet is plain text, exactly the words around the match; the window shows it as text.
- The query is 1 to 200 characters, counted after its whitespace is collapsed, and at most 20 results come back.
"""
from __future__ import annotations

import dataclasses

from server.db.companion_models import ConversationContext
from server.db.models import ArslanMessage

WORD = "photobackup"
URL = "/api/v1/conversations/search"


async def _index(client) -> None:
    from server.db.migrations.versions._0059_messages_fts import upgrade_sync
    async with client.db_maker.kw["bind"].begin() as conn:
        await conn.run_sync(upgrade_sync)            # the trigram index, over the rows already there


async def _seed(client) -> None:
    async with client.db_maker() as db:
        db.add_all([
            ArslanMessage(conversation_id="listed", role="user", content=f"sort the {WORD} folder <img src=x onerror=alert(1)>"),
            ArslanMessage(conversation_id="tmp", role="user", content=f"{WORD} in a temporary chat"),
            ArslanMessage(conversation_id="off", role="user", content=f"{WORD} in a no-memory chat"),
            ArslanMessage(conversation_id="sub-1", role="arslan", content=f"{WORD} in a sub-session"),
            ArslanMessage(conversation_id="quick-1", role="user", content=f"{WORD} in a quick question"),
            ConversationContext(id="listed"),
            ConversationContext(id="tmp", temporary=True, no_memory=True, no_learning=True),
            ConversationContext(id="off", no_memory=True),
            ConversationContext(id="sub-1", kind="sub", parent_id="listed"),
            ConversationContext(id="quick-1", kind="quick"),
        ])
        await db.commit()
    await _index(client)


async def test_it_needs_the_token(client, monkeypatch):
    from server import config
    await _seed(client)
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, api_token="secret-tok"))
    refused = await client.get(URL, params={"q": WORD})
    assert refused.status_code == 401, refused.status_code
    assert (await client.get(URL, params={"q": WORD}, headers={"Authorization": "Bearer wrong"})).status_code == 401
    allowed = await client.get(URL, params={"q": WORD}, headers={"Authorization": "Bearer secret-tok"})
    assert allowed.status_code == 200 and [r["conversation_id"] for r in allowed.json()] == ["listed"]


async def test_only_listed_conversations_and_never_temporary_no_memory_or_sub_sessions(client):
    await _seed(client)
    listed = {c["conversation_id"] for c in (await client.get("/api/v1/conversations")).json()}
    assert {"listed", "sub-1"} <= listed and "quick-1" not in listed       # the window lists the sub-session, not the quick one
    found = (await client.get(URL, params={"q": WORD})).json()
    assert [r["conversation_id"] for r in found] == ["listed"]
    assert set(found[0]) == {"conversation_id", "message_id", "who", "when", "snippet"}
    assert found[0]["who"] == "you" and found[0]["when"]


async def test_the_snippet_is_plain_text(client):
    await _seed(client)
    snippet = (await client.get(URL, params={"q": WORD})).json()[0]["snippet"]
    assert snippet == f"sort the {WORD} folder <img src=x onerror=alert(1)>"     # as said: not escaped, not marked up


async def test_short_queries_use_the_like_fallback_with_the_same_exclusions(client):
    async with client.db_maker() as db:
        db.add_all([
            ArslanMessage(conversation_id="listed", role="user", content="去趟银行"),
            ArslanMessage(conversation_id="sub-2", role="user", content="银行的事"),
            ConversationContext(id="sub-2", kind="sub", parent_id="listed"),
        ])
        await db.commit()
    found = (await client.get(URL, params={"q": "银行"})).json()
    assert [(r["conversation_id"], r["snippet"]) for r in found] == [("listed", "去趟银行")]


async def test_the_length_limits(client):
    assert (await client.get(URL, params={"q": ""})).status_code == 422
    assert (await client.get(URL)).status_code == 422
    assert (await client.get(URL, params={"q": "   "})).status_code == 422
    assert (await client.get(URL, params={"q": "a" * 201})).status_code == 422
    assert (await client.get(URL, params={"q": "a" * 200})).status_code == 200
    long_text = "x" * 600 + f" {WORD} " + "y" * 600
    async with client.db_maker() as db:
        db.add_all([ArslanMessage(conversation_id=f"c{i}", role="user", content=long_text) for i in range(25)])
        await db.commit()
    await _index(client)
    found = (await client.get(URL, params={"q": WORD})).json()
    assert len(found) == 20
    assert all(WORD in r["snippet"] and len(r["snippet"]) <= 240 + 2 for r in found)     # 240 characters and two "…"


async def test_the_200_characters_are_counted_after_the_trim(client):
    # #831 review: 200 visible characters with padding around them fit once the whitespace is collapsed; a limit
    # counted on the raw query would refuse them. Runs of inner spaces collapse too. 201 after the trim is still
    # refused, and the raw input stays bounded.
    async with client.db_maker() as db:
        db.add(ArslanMessage(conversation_id="listed", role="user", content="b" * 200))
        db.add(ConversationContext(id="listed"))
        await db.commit()
    await _index(client)
    padded = await client.get(URL, params={"q": "   " + "b" * 200 + "   "})
    assert padded.status_code == 200, padded.text
    assert [r["conversation_id"] for r in padded.json()] == ["listed"]
    spaced = " ".join(["b" * 99, "b" * 100])                     # 200 after the collapse, 205 before it
    assert (await client.get(URL, params={"q": spaced.replace(" ", "      ")})).status_code == 200
    over = await client.get(URL, params={"q": "  " + "a" * 201 + "  "})
    assert over.status_code == 422 and over.json()["detail"] == {"code": "query_too_long"}
    assert (await client.get(URL, params={"q": " " * 1990 + "a" * 11})).status_code == 422     # past the raw cap
