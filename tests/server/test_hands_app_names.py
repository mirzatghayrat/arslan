"""Hands v2 §15 A19, the backend side. In the user's own use `desktop_look` failed 28 of 32 times:
"WeChat" was two running apps (WeChat and its helper WeChatAppEx), and the backend turned even a
bundle id back into the shared name. Now Hands says which app a request means (`which_app`), the
card is for that app, and Hands is given its bundle id. A window asked for by a title no window has
falls back to the app's only window, or the refusal lists the titles. A row's text no longer makes
a click risky. Hands is faked; nothing is sent to a model."""
import pytest

from server.registry import hands_tools
from tests.server import test_hands_0153 as base

isolated, hands, asks, in_turn, in_job = base.isolated, base.hands, base.asks, base.in_turn, base.in_job

pytestmark = pytest.mark.one_arslan

WECHAT = {"name": "WeChat", "bundle_id": "com.tencent.xinWeChat", "tier": "full", "regular": True}
HELPER = {"name": "WeChat", "bundle_id": "com.tencent.flue.WeChatAppEx", "tier": "full", "regular": False}


def _windows(hands, *titles):
    hands.list_windows = {"ok": True, "app": hands.apps[0], "envelope": {
        "ok": True, "command": "list-windows",
        "data": [{"id": f"w-{n}", "title": t, "pid": 630} for n, t in enumerate(titles, start=1)]}}


async def test_a_name_two_running_apps_share_means_the_app_with_a_dock_icon(hands, asks, in_turn):
    seen, _ = asks
    hands.apps = [HELPER, WECHAT, *hands.apps]
    look = await hands_tools.DesktopLookExecutor().execute({"app": "WeChat"})
    assert look["ok"] is True, look
    assert [f["target"] for f in seen] == ["WeChat"]
    sent = [a["app"] for op, a in hands.calls if op == "snapshot"]
    assert sent and set(sent) == {"com.tencent.xinWeChat"}, "Hands is given the bundle id, not the shared name"
    assert [a["app"] for op, a in hands.calls if op == "which_app"] == ["WeChat"]


async def test_a_bundle_id_stays_a_bundle_id(hands, asks, in_turn):
    hands.apps = [HELPER, WECHAT, *hands.apps]
    look = await hands_tools.DesktopLookExecutor().execute({"app": "com.tencent.xinWeChat"})
    assert look["ok"] is True, look
    assert {a["app"] for op, a in hands.calls if op == "snapshot"} == {"com.tencent.xinWeChat"}


async def test_two_apps_hands_cannot_tell_apart_are_both_named_to_the_model(hands, asks, in_turn):
    seen, _ = asks
    hands.apps = [{**WECHAT, "bundle_id": "com.example.one"}, {**WECHAT, "bundle_id": "com.example.two"}]
    look = await hands_tools.DesktopLookExecutor().execute({"app": "WeChat"})
    assert look["code"] == "app_ambiguous"
    assert "com.example.one" in look["error"] and "com.example.two" in look["error"]
    assert seen == [] and hands.ops("snapshot") == []


async def test_an_app_with_one_window_is_looked_at_there_whatever_title_was_asked(hands, asks, in_turn):
    hands.apps = [WECHAT, *hands.apps]
    _windows(hands, "Weixin")
    look = await hands_tools.DesktopLookExecutor().execute({"app": "WeChat", "window": "微信"})
    assert look["ok"] is True, look
    assert look["text"].startswith("No window of WeChat is titled like “微信”; this is its only window")
    assert [a.get("window_id") for op, a in hands.calls if op == "snapshot" and a.get("max_depth") != 1] == ["w-1"]


async def test_with_several_windows_and_no_title_matching_the_refusal_lists_the_titles(hands, asks, in_turn):
    hands.apps = [WECHAT, *hands.apps]
    _windows(hands, "Weixin", "Moments")
    look = await hands_tools.DesktopLookExecutor().execute({"app": "WeChat", "window": "微信"})
    assert look["code"] == "window_not_found"
    assert "Its windows here:" in look["error"], look["error"]
    assert [a for op, a in hands.calls if op == "snapshot" and a.get("max_depth") != 1] == [], "nothing read"


async def test_the_app_list_says_which_one_is_a_helper(hands, in_turn):
    hands.apps = [HELPER, WECHAT, *hands.apps]
    text = (await hands_tools.DesktopAppsExecutor().execute({}))["text"]
    helper = next(line for line in text.splitlines() if "WeChatAppEx" in line)
    app = next(line for line in text.splitlines() if "xinWeChat" in line)
    assert "background helper" in helper and "background helper" not in app


@pytest.mark.parametrize("role, risky", [("row", False), ("cell", False), ("treeitem", False),
                                         ("textfield", False), ("button", True), ("menuitem", True),
                                         ("link", True), ("group", True), (None, True)])
async def test_a_label_that_is_content_does_not_make_a_click_risky(hands, asks, in_job, role, risky):
    seen, _ = asks
    hands.target = {**hands.target, "role": role, "name": "a note for the delete task"}
    clicked = await hands_tools.DesktopClickExecutor().execute(
        {"app": "Notes", "element": "the note", "ref": "@sfixture0:e3"})
    assert clicked["ok"] is True, clicked
    assert ("desktop_risky" in [f["kind"] for f in seen]) is risky, (role, [f["kind"] for f in seen])
