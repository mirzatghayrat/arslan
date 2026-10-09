"""Hands v2 P2-3 (spec 2026-10-08-0157 §6.3), the backend side: the user's "borrow the front when
needed" switch reaches Hands with every action that may borrow, `front` only when the model asks,
and the model is told what a borrow did — or why nothing was done. Hands is faked."""
import pytest

from server.registry import hands_tools
from server.services import hands_client, hands_service
from tests.server import test_hands_0153 as base

_case = base._case
isolated, hands, asks, in_turn, in_job = base.isolated, base.hands, base.asks, base.in_turn, base.in_job

pytestmark = pytest.mark.one_arslan


def answering(hands, op_name, reply):
    real = hands.call

    async def call(op, args=None, **kw):
        if op == op_name:
            hands.calls.append((op, dict(args or {})))
            return reply
        return await real(op, args, **kw)
    return call


async def test_the_users_switch_goes_with_every_action_that_may_borrow(hands, asks, in_job):
    await hands_tools.DesktopSelectExecutor().execute({"app": "Notes", "element": "Color", "ref": "@sfixture0:e5",
                                                      "value": "Blue"})
    await hands_tools.DesktopClickExecutor().execute({"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"})
    hands_service.update_settings(borrow=False)
    await hands_tools.DesktopPressExecutor().execute({"app": "Notes", "keys": "tab"})
    sent = {op: a for op, a in hands.calls if op in ("select", "click", "press")}
    assert sent["select"]["borrow"] is True and sent["click"]["borrow"] is True
    assert sent["press"]["borrow"] is False
    assert not any("front" in a for a in sent.values()), "front only when the model asks"


async def test_front_goes_to_hands_only_when_the_model_asks(hands, asks, in_job):
    await hands_tools.DesktopClickExecutor().execute({"app": "Notes", "element": "Save", "ref": "@sfixture0:e3",
                                                     "front": True})
    await hands_tools.DesktopPressExecutor().execute({"app": "Notes", "keys": "tab", "front": "yes"})
    sent = [a for op, a in hands.calls if op in ("click", "press")]
    assert sent[0]["front"] is True and "front" not in sent[1]


async def test_the_model_is_told_what_a_borrow_did(hands, asks, in_job, monkeypatch):
    monkeypatch.setattr(hands_client, "call", answering(hands, "select", {
        "ok": True, "app": hands.apps[0], "tier": "full", "mode_used": "borrow", "outcome": "done",
        "envelope": _case("select")["envelope"],
        "borrow": {"front_restored": True, "keys_replayed": 6, "yielded_to_user": True, "waited_ms": 2250,
                   "borrowed_ms": 480}}))
    result = await hands_tools.DesktopSelectExecutor().execute(
        {"app": "Notes", "element": "Color", "ref": "@sfixture0:e5", "value": "Blue"})
    assert result["ok"] is True
    text = result["text"]
    assert "borrowed the front for 480 ms, after waiting 2250 ms for the user to pause typing" in text
    assert "6 key events the user typed meanwhile were held and given back" in text
    assert "The user moved the mouse while it ran" in text


@pytest.mark.parametrize("code, said", [
    ("borrow_off", "turned off"), ("waiting_for_pause", "kept typing"), ("secure_input", "typing a password")])
async def test_why_nothing_was_done_is_said(hands, asks, in_job, monkeypatch, code, said):
    monkeypatch.setattr(hands_client, "call", answering(hands, "select", {
        "ok": False, "refused": {"code": code, "message": "from Hands"}}))
    result = await hands_tools.DesktopSelectExecutor().execute(
        {"app": "Notes", "element": "Color", "ref": "@sfixture0:e5", "value": "Blue"})
    assert result["ok"] is False and result["code"] == code
    assert said in result["error"] and "Nothing was done" in result["error"]
