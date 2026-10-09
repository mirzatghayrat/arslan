"""Hands v2 P2-2 (spec 2026-10-08-0157 §15 A8): the structural-change check, menus pressed in the
background, batches, opening an app, acting inside a chat turn — the backend side, with Hands
faked (the contract fixtures). Nothing is sent to a model."""
import pytest

from server.registry import hands_tools
from server.services import hands_client
from tests.server import test_hands_0153 as base

_case = base._case
isolated, hands, asks, in_turn, in_job = base.isolated, base.hands, base.asks, base.in_turn, base.in_job

pytestmark = pytest.mark.one_arslan

CHANGED = {"ok": False, "refused": {"code": "changed", "message": (
    "Notes changed since your look: a sheet or popover opened on “Groceries”. Nothing was done; look again")}}


async def test_a_changed_window_is_said_as_a_refusal_with_what_changed(hands, asks, in_job, monkeypatch):
    real = hands.call

    async def sheet_opened(op, args=None, **kw):
        if op == "click":
            hands.calls.append((op, dict(args or {})))
            return CHANGED
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", sheet_opened)
    result = await hands_tools.DesktopClickExecutor().execute(
        {"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"})
    assert result["ok"] is False and result["code"] == "changed"
    assert "a sheet or popover opened on “Groceries”" in result["error"]
    assert "look again" in result["error"]
    assert result.get("outcome") in (None, "refused")


async def test_a_menu_item_asks_for_the_app_once_and_risky_items_every_time(hands, asks, in_job):
    seen, _ = asks
    menu = hands_tools.DesktopMenuExecutor()
    for _ in range(2):
        result = await menu.execute({"app": "Notes", "path": ["Format", "Font", "Bold"]})
        assert result["ok"] and result["outcome"] == "sent_unconfirmed"
        assert "“Format › Font › Bold”" in result["text"]
    assert [f["kind"] for f in seen] == ["desktop_app"]
    for _ in range(2):
        assert (await menu.execute({"app": "Notes", "path": ["File", "Delete Note"]}))["ok"]
    risky = [f for f in seen if f["kind"] == "desktop_risky"]
    assert len(risky) == 2 and all("File › Delete Note" in f["target"] for f in risky)
    assert [a["path"] for op, a in hands.calls if op == "menu"] == [["Format", "Font", "Bold"]] * 2 + [
        ["File", "Delete Note"]] * 2


async def test_a_browser_menu_is_refused_before_anyone_is_asked(hands, asks, in_job):
    seen, _ = asks
    result = await hands_tools.DesktopMenuExecutor().execute({"app": "Safari", "path": ["File", "New Window"]})
    assert result["ok"] is False and result["code"] == "app_look_only"
    assert seen == [] and hands.ops("menu") == []


async def test_a_batch_in_a_chat_reply_counts_each_step(hands, asks, in_turn):
    steps = [{"action": "press", "keys": "tab"}] * 7
    result = await hands_tools.DesktopBatchExecutor().execute({"app": "Notes", "steps": steps})
    assert hands.ops("press") == ["press"] * hands_tools.INLINE_ACTIONS
    assert f"stopped at step {hands_tools.INLINE_ACTIONS + 1} (act_in_background)" in result["text"]


async def test_a_combo_that_went_to_its_menu_item_says_so(hands, asks, in_job, monkeypatch):
    real = hands.call

    async def routed(op, args=None, **kw):
        if op == "press":
            hands.calls.append((op, dict(args or {})))
            return {"ok": True, "outcome": "sent_unconfirmed", "route": "menu_item", "keys": "cmd+b",
                    "menu_item": ["Format", "Font", "Bold"], "app": hands.apps[0], "tier": "full"}
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", routed)
    result = await hands_tools.DesktopPressExecutor().execute({"app": "Notes", "keys": "cmd+b"})
    assert result["ok"] is True
    assert "went to the menu item with that shortcut: “Format › Font › Bold”" in result["text"]


async def test_a_batch_runs_its_steps_with_every_check_and_ends_with_a_look(hands, asks, in_job):
    seen, _ = asks
    hands.capture = {"ok": True, "capture": {"ok": True, "window_id": 85125, "title": "Hands Fixture",
                                             "onscreen": True, "frame": {"x": 0, "y": 0, "width": 10, "height": 10},
                                             "scale": 1.0, "width": 10, "height": 10, "mime": "image/jpeg",
                                             "data": "AAAA"}}
    await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})   # refs come from a look
    seen.clear()
    hands.calls.clear()
    result = await hands_tools.DesktopBatchExecutor().execute({"app": "Notes", "steps": [
        {"action": "type", "element": "Title", "ref": "@sfixture0:e1", "text": "Groceries"},
        {"action": "click", "element": "Save", "ref": "@sfixture0:e3"},
        {"action": "menu", "path": ["Format", "Font", "Bold"]}]})
    assert result["ok"] is True, result
    assert result["text"].startswith("Batch in Notes: 3 of 3 steps went through.")
    assert "The window now:" in result["text"]
    assert result["images"] == [{"mime_type": "image/jpeg", "data": "AAAA"}]
    assert [f["kind"] for f in seen] == ["desktop_app"]          # one card for the app, as single calls
    assert hands.ops("set_value", "click", "menu", "snapshot") == ["set_value", "click", "menu", "snapshot"]


async def test_a_batch_stops_at_the_first_step_that_did_not_go_through(hands, asks, in_job, monkeypatch):
    real = hands.call

    async def changed_on_click(op, args=None, **kw):
        if op == "click":
            hands.calls.append((op, dict(args or {})))
            return CHANGED
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", changed_on_click)
    result = await hands_tools.DesktopBatchExecutor().execute({"app": "Notes", "steps": [
        {"action": "click", "element": "Save", "ref": "@sfixture0:e3"},
        {"action": "menu", "path": ["Format", "Font", "Bold"]}]})
    assert result["ok"] is False and result["code"] == "batch_stopped"
    assert "0 of 2 steps went through; stopped at step 1 (changed)" in result["text"]
    assert hands.ops("menu") == [], "nothing after the stop ran"
    assert hands.ops("snapshot") == ["snapshot"], "and it still ends with a look"


async def test_a_batch_is_one_app_and_at_most_eight_steps(hands, asks, in_job):
    nine = [{"action": "press", "keys": "tab"}] * 9
    assert (await hands_tools.DesktopBatchExecutor().execute({"app": "Notes", "steps": nine}))["code"] == "bad_request"
    result = await hands_tools.DesktopBatchExecutor().execute({"app": "Notes", "steps": [
        {"action": "press", "keys": "tab", "app": "Safari"}]})
    pressed = [a.get("app") for op, a in hands.calls if op == "press"]
    assert pressed == ["Notes"], f"a step cannot change the app: {pressed}"
    bad = await hands_tools.DesktopBatchExecutor().execute({"app": "Notes", "steps": [{"action": "drag"}]})
    assert "0 of 1 steps went through; step 1: unknown action “drag”" in bad["text"]
