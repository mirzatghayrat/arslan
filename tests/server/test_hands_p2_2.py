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


async def test_menus_are_acted_in_background_work_only(hands, asks, in_turn):
    result = await hands_tools.DesktopMenuExecutor().execute({"app": "Notes", "path": ["Format", "Font", "Bold"]})
    assert result["code"] == "act_in_background" and hands.ops("menu") == []


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
