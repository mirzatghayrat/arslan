"""v0.1.64 CAP11 step a: a "no" to a capability card carries the user's typed reason to the model in the same turn, and a
plain no is accepted from any surface while a yes from anywhere but the asking window is still swallowed.

Before this, the window's reply kept its note in the approval decision (`approvals.answer`) but the window's capability
asker returned only approved/keys/folders/kept, and `capability_flow.propose` answered every decline with a fixed
sentence: the model never learnt why the user said no. The note is bounded as every other card's "No" note is
(`permissions.decide`: stripped, at most 500 characters) and is the user's own words, so it rides in the sentence as
"They said: …" exactly as a declined permission card's does.
"""
import copy

import pytest

from server.orchestrator import tool_loop
from server.services import approvals, capability_flow, capability_search
from tests.server import test_cap8b_memory_import as base
from tests.server.test_arslan_loop import _tc
from tests.server.test_cap8b_registered_tool import _Model
from tests.server.test_capability_flow import CAND, shown
from tests.server.test_run_command_confirm_flow import _collect_until

window_client = base.window_client

REASON = "I only use Numbers, not Excel"


@pytest.fixture(autouse=True)
def _prepared_without_network(fake_capability_prepare):
    """An MCP card is prepared first (license, runtime, lock); here without the network."""


def _declines(note=None):
    async def ask(card):
        answer = {"approved": False, "call_id": "cap-x", "keys": {}, "folders": []}
        return answer if note is None else {**answer, "note": note}
    return ask


# ── the flow tells the model what the user said ───────────────────────────────

async def test_a_declined_capability_tells_the_model_the_users_reason(execution_db):
    shown("c-why", CAND)
    out = await capability_flow.propose({"candidate_id": CAND["id"], "why": "x"}, conversation_id="c-why",
                                        ask=_declines(f"  {REASON}\n"), emit=lambda e: None)
    assert out["ok"] is False and out["declined"] is True
    assert f"They said: {REASON}" in out["note"]
    assert "do not propose it again now" in out["note"]


async def test_a_decline_without_a_reason_reads_as_before(execution_db):
    shown("c-plain", CAND)
    for note in (None, "", "   "):
        out = await capability_flow.propose({"candidate_id": CAND["id"], "why": "x"}, conversation_id="c-plain",
                                            ask=_declines(note), emit=lambda e: None)
        assert out["declined"] is True and "They said" not in out["note"], note
        assert out["note"] == ("The user did not add it (declined). Do the task another way or say what is missing; "
                               "do not propose it again now.")


async def test_the_reason_is_bounded_as_every_cards_no_note_is(execution_db):
    shown("c-long", CAND)
    out = await capability_flow.propose({"candidate_id": CAND["id"], "why": "x"}, conversation_id="c-long",
                                        ask=_declines("y" * 2000), emit=lambda e: None)
    assert "y" * 500 in out["note"] and "y" * 501 not in out["note"]


# ── the real socket: the window's "No" with a reason reaches the model's tool answer ──

def test_the_windows_no_with_a_reason_reaches_the_model_in_the_same_turn(window_client, monkeypatch):
    def seen(conversation_id, candidate_id):
        return copy.deepcopy(CAND) if candidate_id == CAND["id"] else None
    monkeypatch.setattr(capability_search, "seen", seen)
    model = _Model([_tc("propose_capability", {"candidate_id": CAND["id"], "why": "read the formulas"})], "Understood.")
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    with window_client.websocket_connect("/ws/arslan/main") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "Read the formulas in budget.xlsx"})
        card = _collect_until(window, "propose_capability")[-1]
        window.send_json({"type": "cancel_capability", "call_id": card["call_id"], "note": REASON})
        _collect_until(window, "stream_end", max_frames=80)
    answer = model.tool_answers()[-1]
    assert '"declined": true' in answer and REASON in answer


# ── who may say no, and who may not say yes ───────────────────────────────────

@pytest.fixture
def _clean():
    approvals._reset_for_tests()
    yield
    approvals._reset_for_tests()


async def test_a_phone_no_to_the_capability_proposal_declines_it_with_the_reason(_clean):
    """The install card itself (`propose_capability`, not only a card carrying the `capability` kind): the phone's plain
    no is accepted and keeps its reason; the card reads as answered on the phone."""
    pending = approvals.open_card("conv-p", {"type": "propose_capability", "call_id": "cap-p", "keys": [], "folders": []},
                                  broadcast=False)
    try:
        assert approvals.answer({"type": "cancel_capability", "call_id": "cap-p", "source": "phone", "note": REASON})
        decision = pending.future.result()
        assert (decision["approved"], decision["by"], decision["note"]) == (False, "phone", REASON)
        assert decision["extras"] == {}
    finally:
        approvals.close_card(pending)


async def test_a_phone_yes_to_the_capability_proposal_is_still_swallowed(_clean):
    pending = approvals.open_card("conv-q", {"type": "propose_capability", "call_id": "cap-q", "keys": [], "folders": []},
                                  broadcast=False)
    try:
        assert approvals.answer({"type": "confirm_capability", "call_id": "cap-q", "source": "phone"}) is True
        assert not pending.future.done()
        assert approvals.answer({"type": "cancel_capability", "call_id": "cap-q", "source": "phone"}) is True
        assert pending.future.result()["approved"] is False      # the swallowed yes left the card open for the no
    finally:
        approvals.close_card(pending)
