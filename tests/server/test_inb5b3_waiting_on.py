"""INB5b-3 (v0.1.64): a waiting row says what it waits on.

#590's re-check: whether a row waits on a card or on a reminder must be clear, since an open "the job stopped" reminder makes the job's
row read "waiting" over its own outcome. The window's list says `waiting_on`: "card" (a card is open, or one went unanswered while you
were away) or "reminder" (a job that stopped left one). A card wins: it is a decision, the reminder an offer. Phones get no new field:
their list is built field by field (⓪Plan, 2026-11-01: the window's list only, as phone_state keeps phones on their old values).
"""
from server.services import approvals, desktop_status
from tests.server.test_inb5_waiting import _add, _chat, _item, _refused


async def _window_rows(client) -> dict[str, dict]:
    return {row["conversation_id"]: row for row in (await client.get("/api/v1/conversations")).json()}


async def test_a_waiting_row_says_whether_it_waits_on_a_card_or_a_reminder(client, monkeypatch):
    monkeypatch.setattr(approvals, "all_pending", lambda: [{"call_id": "c1", "conversation_id": "chat-a"}])
    island = desktop_status.island_feed
    monkeypatch.setattr(desktop_status, "island_feed", lambda: {**island(), "awaiting_conversations": ["chat-e"]})
    await _add(client, *_chat("chat-a"), *_chat("chat-b"), *_chat("chat-c"), *_chat("chat-d"), *_chat("chat-e"),
               _item(1, "job_followup", "job:1", conversation_id="chat-a"),        # a card and a reminder: the card wins
               _refused("chat-b"),                                                  # a card nobody could answer while you were away
               _item(2, "job_followup", "job:2", conversation_id="chat-c"))        # a stopped job's reminder, and nothing else
    rows = await _window_rows(client)
    assert {cid: (rows[cid]["state"], rows[cid]["waiting_on"]) for cid in ("chat-a", "chat-b", "chat-c", "chat-d", "chat-e")} == {
        "chat-a": ("waiting", "card"), "chat-b": ("waiting", "card"), "chat-c": ("waiting", "reminder"),
        "chat-d": ("done_unseen", None), "chat-e": ("waiting", "card")}            # d: not waiting (a reply not seen yet); e: the island's card


async def test_phones_get_no_new_field(client):
    await _add(client, *_chat("chat-c"), _item(2, "job_followup", "job:2", conversation_id="chat-c"))
    body = (await client.get("/api/v1/phone/conversations?limit=50")).json()
    [row] = [r for r in body["conversations"] if r["id"] == "chat-c"]
    assert "waiting_on" not in row
    assert set(row) == {"id", "title", "updated_at", "kind", "state", "origin", "preview", "files"}
