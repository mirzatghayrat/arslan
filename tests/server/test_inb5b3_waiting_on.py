"""INB5b-3 (v0.1.64): a waiting row says what it waits on.

#590's re-check: whether a row waits on a card or on a reminder must be clear, since an open "the job stopped" reminder makes the job's
row read "waiting" over its own outcome. The window's list says `waiting_on`: "card" (a card is open), "away" (a card went unanswered
while you were away: nothing is left to approve, only the "not done while you were away" list; ⓪Plan's review of PR 614, N2) or
"reminder" (a job that stopped left one). A card wins, then an away entry: a card is a decision, the reminder an offer. Phones get no
new field: their list is built field by field (⓪Plan, 2026-11-01: the window's list only, as phone_state keeps phones on their old
values).
"""
from server.services import approvals, desktop_status
from tests.server.test_inb5_waiting import _add, _chat, _item, _refused


async def _window_rows(client) -> dict[str, dict]:
    return {row["conversation_id"]: row for row in (await client.get("/api/v1/conversations")).json()}


async def test_a_waiting_row_says_whether_it_waits_on_a_card_an_away_entry_or_a_reminder(client, monkeypatch):
    monkeypatch.setattr(approvals, "all_pending", lambda: [{"call_id": "c1", "conversation_id": "chat-a"},
                                                           {"call_id": "c2", "conversation_id": "chat-g"}])
    island = desktop_status.island_feed
    monkeypatch.setattr(desktop_status, "island_feed", lambda: {**island(), "awaiting_conversations": ["chat-e"]})
    await _add(client, *_chat("chat-a"), *_chat("chat-b"), *_chat("chat-c"), *_chat("chat-d"), *_chat("chat-e"), *_chat("chat-f"),
               *_chat("chat-g"),
               _item(1, "job_followup", "job:1", conversation_id="chat-a"),        # a card and a reminder: the card wins
               _refused("chat-b"),                                                  # a card nobody could answer while you were away
               _item(2, "job_followup", "job:2", conversation_id="chat-c"),        # a stopped job's reminder, and nothing else
               _item(5, "job_followup", "job:5", conversation_id="chat-e"),        # the island's card and a reminder: the card wins
               _refused("chat-f"), _item(6, "job_followup", "job:6", conversation_id="chat-f"),  # away and a reminder: away
               _refused("chat-g"))                                                  # a card and an away entry: the card wins
    rows = await _window_rows(client)
    assert {cid: (rows[cid]["state"], rows[cid]["waiting_on"]) for cid in rows if cid.startswith("chat-")} == {
        "chat-a": ("waiting", "card"), "chat-b": ("waiting", "away"), "chat-c": ("waiting", "reminder"),
        "chat-d": ("done_unseen", None), "chat-e": ("waiting", "card"), "chat-f": ("waiting", "away"),
        "chat-g": ("waiting", "card")}                                              # d: not waiting (a reply not seen yet)


async def test_phones_get_no_new_field(client):
    await _add(client, *_chat("chat-c"), _item(2, "job_followup", "job:2", conversation_id="chat-c"))
    body = (await client.get("/api/v1/phone/conversations?limit=50")).json()
    [row] = [r for r in body["conversations"] if r["id"] == "chat-c"]
    assert "waiting_on" not in row
    assert set(row) == {"id", "title", "updated_at", "kind", "state", "origin", "preview", "files"}
