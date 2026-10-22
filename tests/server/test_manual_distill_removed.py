"""C8-5 (v0.1.63): the manual "Distill" action is gone, route and menu item both.

It folded a conversation's spawn chats into memory by hand; since C1 it only did
anything for old conversations that had spawns (card C8). The web half is pinned in
web/src/__tests__/thread-row-menu.test.tsx (the menu no longer offers it).
"""
AUTH: dict[str, str] = {}


async def test_the_manual_distill_route_is_gone(client):
    # Positive control: the conversations router itself still answers.
    assert (await client.get("/api/v1/conversations", headers=AUTH)).status_code == 200
    r = await client.post("/api/v1/conversations/conv-x/distill", headers=AUTH)
    assert r.status_code in (404, 405)


def test_nothing_writes_the_manual_distill_recap_event_any_more():
    """The route was the only writer of the `distill` recap event (and its
    `recap.distill.*` keys). Old rows stay in ConversationEvent and still read back."""
    from server.api import conversations

    assert not hasattr(conversations, "_distill_event")
    assert not hasattr(conversations, "conversation_distill")
