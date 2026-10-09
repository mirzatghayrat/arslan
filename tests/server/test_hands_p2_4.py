"""Hands v2 P2-4 (spec 2026-10-08-0157 §7): apps allowed for good, a job inheriting its
conversation's yes, apps never screenshotted, one card for several apps, and Settings' API —
with Hands faked. Nothing is sent to a model."""
import pytest

from server.api import hands as hands_api
from server.registry import hands_tools
from server.services import background_jobs, hands_client, hands_service
from server.services import personal_context as pc
from tests.server import test_hands_0153 as base

isolated, hands, asks, in_turn, in_job = base.isolated, base.hands, base.asks, base.in_turn, base.in_job

pytestmark = pytest.mark.one_arslan

CLICK = {"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"}


def kinds(seen):
    return [f["kind"] for f in seen]


def test_new_settings_are_empty_by_default_and_saved():
    s = hands_service.settings()
    assert s["always"] == [] and s["no_screenshots"] == []
    hands_service.update_settings(always=[{"bundle_id": "com.apple.Notes", "name": "Notes"}, {"name": "no id"}],
                                  no_screenshots=["Mail", "mail", " ", "Messages"])
    s = hands_service.settings()
    assert [a["bundle_id"] for a in s["always"]] == ["com.apple.Notes"]
    assert s["no_screenshots"] == ["Mail", "Messages"]
    assert hands_service.always_allowed("com.apple.Notes") and not hands_service.always_allowed("com.apple.Mail")
    assert hands_service.no_screenshots("mail", "") and hands_service.no_screenshots("", "messages")


async def test_an_app_allowed_for_good_is_not_asked_again_but_risky_steps_still_are(hands, asks, in_job):
    seen, _ = asks
    hands_service.update_settings(always=[{"bundle_id": "com.apple.Notes", "name": "Notes"}])
    assert (await hands_tools.DesktopLookExecutor().execute({"app": "Notes"}))["ok"]
    assert (await hands_tools.DesktopClickExecutor().execute(CLICK))["ok"]
    assert seen == []
    hands.target = {**hands.target, "name": "Delete"}
    await hands_tools.DesktopClickExecutor().execute({**CLICK, "element": "Delete", "ref": "@sfixture0:e4"})
    assert kinds(seen) == ["desktop_risky"]


async def test_a_job_inherits_what_its_conversation_allowed(hands, asks):
    seen, _ = asks
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r1", conversation_id="c1")):
        assert (await hands_tools.DesktopClickExecutor().execute(CLICK))["ok"]          # a chat reply acts
    assert kinds(seen) == ["desktop_app"]
    token = background_jobs._inside_job.set("job-7")
    try:
        with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r2", conversation_id="c1")):
            assert (await hands_tools.DesktopClickExecutor().execute(CLICK))["ok"]
    finally:
        background_jobs._inside_job.reset(token)
    assert kinds(seen) == ["desktop_app"], "the job did not ask again"


async def test_an_app_never_screenshotted_is_read_as_text_only(hands, asks, in_turn):
    hands_service.update_settings(no_screenshots=["Notes"])
    hands.capture = {"ok": True, "capture": {"ok": True, "data": "AAAA", "mime": "image/jpeg"}}
    result = await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
    assert "images" not in result and hands.ops("capture_window") == []


async def test_one_card_for_several_apps_then_no_more_cards(hands, asks, in_job):
    seen, _ = asks
    result = await hands_tools.DesktopAccessExecutor().execute(
        {"apps": ["Notes", "Safari", "Keychain Access"], "why": "copy the list from the web page into a note"})
    assert result["ok"] is True
    cards = [f for f in seen if f["kind"] == "desktop_app"]
    assert len(cards) == 1
    assert "· Notes — look and act" in cards[0]["detail"] and "· Safari — look only" in cards[0]["detail"]
    assert "Keychain Access" not in cards[0]["detail"] and "Not included: Keychain Access (app_denied)" in result["text"]
    await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
    await hands_tools.DesktopLookExecutor().execute({"app": "Safari"})
    assert (await hands_tools.DesktopClickExecutor().execute(CLICK))["ok"]
    assert len(seen) == 1, "neither looking nor acting asked again"


async def test_a_declined_access_card_allows_nothing(hands, asks, in_job):
    seen, answer = asks
    answer["value"] = False
    result = await hands_tools.DesktopAccessExecutor().execute({"apps": ["Notes"], "why": "x"})
    assert result["code"] == "declined"
    answer["value"] = True
    await hands_tools.DesktopClickExecutor().execute(CLICK)
    assert kinds(seen) == ["desktop_app", "desktop_app"], "acting still asks after a declined card"


async def test_settings_api_keeps_always_by_bundle_id_and_asks_for_screen_recording(hands, monkeypatch):
    monkeypatch.setattr(hands_client, "available", lambda: True)
    added = await hands_api.add_always(hands_api.AlwaysApp(app="Notes"))
    assert added["ok"] and added["always"][0]["bundle_id"] == "com.apple.Notes" and added["always"][0]["since"]
    again = await hands_api.add_always(hands_api.AlwaysApp(app="notes"))
    assert len(again["always"]) == 1
    missing = await hands_api.add_always(hands_api.AlwaysApp(app="Not Running"))
    assert missing["ok"] is False and missing["code"] == "app_not_running"
    removed = await hands_api.remove_always("com.apple.Notes")
    assert removed["always"] == []
    await hands_api.ask_permission(hands_api.Permission(kind="screen"))
    assert ("request_permission", {"kind": "screen"}) in hands.calls
