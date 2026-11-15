"""v0.1.64 CAP11 step a, the Bridge frame half: capability cards reach the phone view-only.

The Mac sets `phone_can_approve` on every card it opens (`approvals.open_card`), false for a capability card in
v0.1.64, and refuses a phone yes whenever its own copy of the card says false; whatever the phone's answer carries is
never read. A phone no is accepted. The install card carries three optional fields for the phone (`phone`: `source`,
`abilities`, `checks`), built by the Mac within the spec's limits (docs/specs/mobile-bridge-protocol.md §5.13).
In a turn the iPhone started, a capability card no longer skips the Bridge's socket; a bare-run command card still does.
"""
import copy

import pytest

from server.orchestrator import tool_loop
from server.services import approvals, capability_flow, capability_search
from tests.server import test_cap8b_memory_import as base
from tests.server.test_arslan_loop import _tc
from tests.server.test_cap8b_registered_tool import _Model
from tests.server.test_capability_flow import CAND
from tests.server.test_run_command_confirm_flow import _collect_until

window_client = base.window_client


@pytest.fixture
def _clean():
    approvals._reset_for_tests()
    yield
    approvals._reset_for_tests()


CARDS = {
    "install card": ({"type": "propose_capability", "call_id": "k-cap", "keys": [], "folders": []}, False),
    "capability kind on an action": ({"type": "propose_action", "call_id": "k-act", "kind": "app",
                                      "perm_kind": "capability", "options": ["once"]}, False),
    "an app card": ({"type": "propose_action", "call_id": "k-app", "kind": "app", "perm_kind": "app",
                     "options": ["task"]}, True),
    "a write": ({"type": "propose_workspace_write", "call_id": "k-w", "workspace": "/w", "action": "Write",
                 "path": "a.md"}, True),
}


# ── the Mac sets the field, and its refusal follows it ────────────────────────

@pytest.mark.parametrize("name", CARDS)
async def test_every_opened_card_says_whether_a_phone_yes_counts_and_the_answer_follows_it(_clean, name):
    frame, expected = copy.deepcopy(CARDS[name][0]), CARDS[name][1]
    pending = approvals.open_card("conv-f", frame, broadcast=False)
    try:
        assert pending.frame["phone_can_approve"] is expected
        kind = frame["type"].removeprefix("propose_")
        # The phone claims the card is phone-approvable: never read.
        assert approvals.answer({"type": f"confirm_{kind}", "call_id": frame["call_id"], "source": "phone",
                                 "phone_can_approve": True})
        assert pending.future.done() is expected, name
        if expected:
            assert pending.future.result()["approved"] is True and pending.future.result()["by"] == "phone"
    finally:
        approvals.close_card(pending)


async def test_a_phone_yes_is_refused_by_the_cards_own_field_not_only_by_window_only(_clean, monkeypatch):
    """The phone's refusal reads `phone_can_approve`: a card the Mac says isn't phone-approvable is refused even when it
    isn't window-only (the high_risk_mac_only switch, once it exists, folds in there)."""
    monkeypatch.setattr(approvals, "phone_can_approve", lambda frame: False)
    frame = copy.deepcopy(CARDS["a write"][0])
    pending = approvals.open_card("conv-g", frame, broadcast=False)
    try:
        assert approvals.answer({"type": "confirm_workspace_write", "call_id": "k-w", "source": "phone"})
        assert not pending.future.done()
        assert approvals.answer({"type": "confirm_workspace_write", "call_id": "k-w"})      # the window still may
        assert pending.future.result()["approved"] is True
    finally:
        approvals.close_card(pending)


async def test_a_phone_no_on_a_capability_card_is_accepted_with_its_note(_clean):
    frame = copy.deepcopy(CARDS["install card"][0])
    pending = approvals.open_card("conv-d", frame, broadcast=False)
    try:
        assert approvals.answer({"type": "cancel_capability", "call_id": "k-cap", "source": "phone", "note": "not now"})
        decision = pending.future.result()
        assert decision["approved"] is False and decision["by"] == "phone" and decision["note"] == "not now"
    finally:
        approvals.close_card(pending)


def test_in_a_phone_turn_only_a_bare_run_skips_the_phone_never_a_capability_card():
    assert approvals.skips_phone(CARDS["install card"][0]) is False
    assert approvals.skips_phone(CARDS["capability kind on an action"][0]) is False
    assert approvals.skips_phone(CARDS["an app card"][0]) is False
    bare = {"type": "propose_run_command", "call_id": "k-b", "command": "osascript",
            "argv": ["-e", 'tell application "Reminders" to count lists'], "pretty": "osascript"}
    assert approvals.window_only(bare) and approvals.skips_phone(bare) is True


# ── the three optional fields, within the spec's limits ───────────────────────

def test_the_phone_fields_come_from_the_card_and_are_cut_to_the_limits():
    card = {"kind": "mcp", "name": "excel", "source_url": "https://github.com/x/" + "y" * 400, "repo": "x/y",
            "network": True, "remote_host": None, "folders": [f"/Users/me/f{i}" for i in range(12)],
            "keys": [{"name": "TOKEN_" + "k" * 300}], "shared_folder": False,
            "lock": {"sha256": "ab" * 32, "count": 3, "packages": []},
            "vulns": {"state": "checked", "count": 2, "highest": "HIGH", "packages": 3, "complete": True}}
    out = capability_flow.phone_fields(card)
    assert len(out["source"]) == 200 and out["source"].startswith("https://github.com/x/")
    assert 1 <= len(out["abilities"]) <= 8 and all(len(a) <= 120 for a in out["abilities"])
    assert out["abilities"][0] == "Uses the network"
    checks = {c["name"]: c for c in out["checks"]}
    assert checks["osv"]["result"] == "warn" and "2 known" in checks["osv"]["detail"]
    assert checks["lock"]["result"] == "pass" and ("ab" * 6) in checks["lock"]["detail"]
    assert all(len(c.get("detail", "")) <= 160 for c in out["checks"])


def test_empty_lists_are_left_out_and_osv_not_asked_is_not_run():
    out = capability_flow.phone_fields({"kind": "skill", "name": "s", "source_url": None, "repo": "a/b",
                                        "network": False, "folders": [], "keys": [], "shared_folder": False,
                                        "vulns": {"state": "not_checked", "why": "osv_did_not_answer"}})
    assert out["source"] == "a/b" and "abilities" not in out
    assert out["checks"] == [{"name": "osv", "result": "not_run", "detail": "OSV.dev did not answer"}]
    assert capability_flow.phone_fields({"kind": "skill", "name": "s"}) == {}


def test_a_skill_scan_is_a_check():
    out = capability_flow.phone_fields({"kind": "skill", "name": "s", "source_url": "https://x", "shared_folder": True,
                                        "commit": "c" * 40, "scan": {"level": "notes", "findings": [{}, {}]}})
    checks = {c["name"]: c for c in out["checks"]}
    assert checks["scan"] == {"name": "scan", "result": "warn", "detail": "2 notes"}
    assert checks["pinned"]["result"] == "pass" and checks["pinned"]["detail"].startswith("c" * 12)
    assert out["abilities"] == ["Installs into the shared skills folder"]


# ── the real socket: a phone turn's install card reaches the Bridge, view-only ──

@pytest.fixture
def _prepared_without_network(fake_capability_prepare):
    """An MCP card is prepared first (license, runtime, lock); here without the network."""


def test_a_phone_turns_install_card_reaches_the_bridge_and_only_its_no_counts(window_client, monkeypatch,
                                                                             _prepared_without_network):
    def seen(conversation_id, candidate_id):
        return copy.deepcopy(CAND) if candidate_id == CAND["id"] else None
    monkeypatch.setattr(capability_search, "seen", seen)
    model = _Model([_tc("propose_capability", {"candidate_id": CAND["id"], "why": "read the formulas"})], "Understood.")
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    with window_client.websocket_connect("/ws/arslan/main") as bridge:
        bridge.receive_json()
        bridge.send_json({"type": "user_message", "content": "Read budget.xlsx", "source": "phone"})
        card = _collect_until(bridge, "propose_capability")[-1]
        assert card["phone_can_approve"] is False
        assert card["phone"]["source"] == CAND["source_url"]
        assert {c["name"] for c in card["phone"]["checks"]} >= {"osv", "lock"}
        bridge.send_json({"type": "confirm_capability", "call_id": card["call_id"], "source": "phone",
                          "phone_can_approve": True})
        bridge.send_json({"type": "cancel_capability", "call_id": card["call_id"], "source": "phone"})
        _collect_until(bridge, "stream_end", max_frames=80)
    assert '"declined": true' in model.tool_answers()[-1]
