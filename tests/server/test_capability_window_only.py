"""0.1.61 §A4 (PR 2b final review, M6): a card whose permission kind is `capability` is answered only where its whole card is shown.

Installing code wants the whole card (0.1.57), so a new capability is allowed from the asking window only. The phone never gets
such a card (the Bridge drops it) and the island refuses it, but a `propose_action` frame that carries `perm_kind: "capability"` was
approved by the Inbox and by a phone answer all the same: only the card TYPE `propose_capability` was window-only. Now the kind is
too, on every card type: a yes from the phone is swallowed and a yes from the Inbox or the island is "open in Arslan" (403);
saying no is always allowed, and the window's own yes still works.
"""
import httpx
import pytest
from fastapi import FastAPI

from server import auth
from server.api.approvals import router
from server.services import approvals
from server.ws import protocol

CAPABILITY = {"perm_kind": "capability", "options": ["once"], "title": "Add the srv tool?"}

#: A card of each type that may carry a permission kind, as the confirm/cancel reply names it.
FRAMES = {
    "action": lambda cid: protocol.propose_action(cid, "capability", "srv", "adds a tool"),
    "mac_script": lambda cid: protocol.propose_action(cid, "mac_script", "Notes", 'tell application "Notes" to get name'),
    "command": lambda cid: protocol.propose_run_command(cid, "npx", ["srv"]),
    "write": lambda cid: protocol.propose_workspace_write(cid, "~/Arslan", "write", "notes.md"),
    "schedule": lambda cid: protocol.propose_schedule(cid, "Morning brief", "cron: 0 9 * * *"),
}
KIND_OF_REPLY = {"action": "action", "mac_script": "action", "command": "run_command", "write": "workspace_write", "schedule": "schedule"}


@pytest.fixture(autouse=True)
def _clean():
    approvals._reset_for_tests()
    yield
    approvals._reset_for_tests()


@pytest.fixture
async def api(monkeypatch):
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": "Bearer synthetic-token"}) as client:
        yield client


def _open(card: str, **extra) -> approvals.Pending:
    return approvals.open_card("conv", FRAMES[card]("k1") | CAPABILITY | extra, broadcast=False)


def _reply(card: str, approve: bool, **extra) -> dict:
    verb = "confirm" if approve else "cancel"
    return {"type": f"{verb}_{KIND_OF_REPLY[card]}", "call_id": "k1", **extra}


@pytest.mark.parametrize("card", sorted(FRAMES))
async def test_a_phone_yes_to_a_capability_card_is_swallowed(card):
    pending = _open(card)
    assert approvals.answer(_reply(card, True, source="phone")) is True          # swallowed, as a late reply is
    assert not pending.future.done()


@pytest.mark.parametrize("card", sorted(FRAMES))
@pytest.mark.parametrize("source", ["inbox", "island"])
async def test_an_inbox_or_island_yes_to_a_capability_card_is_open_in_arslan(card, source):
    pending = _open(card)
    with pytest.raises(approvals.OpenInArslan):
        approvals.answer_by_id("k1", True, source=source)
    assert not pending.future.done()
    # nor does a reply of that source reach the card by the socket rule
    assert approvals.answer(_reply(card, True, source=source)) is True
    assert not pending.future.done()


@pytest.mark.parametrize("card", sorted(FRAMES))
@pytest.mark.parametrize("source", ["phone", "inbox", "island"])
async def test_saying_no_to_a_capability_card_is_allowed_from_anywhere(card, source):
    pending = _open(card)
    if source == "phone":
        approvals.answer(_reply(card, False, source="phone", note="no"))
    else:
        assert approvals.answer_by_id("k1", False, source=source, note="no") is True
    assert pending.future.done() and pending.future.result()["approved"] is False
    assert pending.future.result()["by"] == source


@pytest.mark.parametrize("card", sorted(FRAMES))
async def test_the_asking_windows_yes_to_a_capability_card_still_works(card):
    pending = _open(card)
    approvals.answer(_reply(card, True))                                          # a window sends no source
    assert pending.future.done()
    decision = pending.future.result()
    assert (decision["approved"], decision["by"], decision["scope"]) == (True, "mac", "once")
    assert "extras" not in decision, "the capability proposal's keys and folders belong to the propose_capability type alone"


async def test_the_inbox_route_says_open_in_arslan_and_nothing_is_decided(api):
    pending = _open("action")
    refused = await api.post("/api/v1/approvals/k1/answer", json={"approve": True, "source": "inbox"})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "open_in_arslan"
    assert not pending.future.done()
    still_there = {row["call_id"]: row for row in (await api.get("/api/v1/approvals/pending")).json()}
    assert still_there["k1"]["island_ok"] is False
    assert (await api.post("/api/v1/approvals/k1/answer", json={"approve": False, "source": "inbox"})).status_code == 200
    assert pending.future.result()["approved"] is False


@pytest.mark.parametrize("perm_kind", ["app", "site", "shortcut", "command", "money", "Capability", " capability", ["capability"], None, ""])
async def test_only_the_capability_kind_is_window_only(perm_kind):
    """Every other kind keeps the rule it had: the Inbox and the phone answer, the island by its own rule, and a kind that merely
    looks like the name (another case, spaces, a list) is not it."""
    for source in ("inbox", "phone"):
        approvals._reset_for_tests()
        pending = approvals.open_card("conv", FRAMES["action"]("k1") | {"perm_kind": perm_kind, "options": ["task", "conversation"]},
                                      broadcast=False)
        if source == "inbox":
            assert approvals.answer_by_id("k1", True, source="inbox") is True
        else:
            approvals.answer(_reply("action", True, source="phone"))
        assert pending.future.done() and pending.future.result()["approved"] is True, (perm_kind, source)


async def test_the_capability_proposal_type_is_still_window_only_and_keeps_its_extras():
    pending = approvals.open_card("conv", {"type": "propose_capability", "call_id": "k1", "name": "srv", "keys": [], "folders": []},
                                  broadcast=False)
    with pytest.raises(approvals.OpenInArslan):
        approvals.answer_by_id("k1", True, source="inbox")
    approvals.answer({"type": "confirm_capability", "call_id": "k1", "source": "phone"})
    assert not pending.future.done()
    approvals.answer({"type": "confirm_capability", "call_id": "k1", "keys": {}, "folders": []})
    assert pending.future.done() and "extras" in pending.future.result()
