"""Hands v2 look (spec 2026-10-08-0157 §4.1–4.2, §15 A8): a look comes with a screenshot of the
window, each element's place in it, and what changed since the last look of that window —
with Hands faked (the contract fixtures), nothing sent to a model."""
import copy
import json

import pytest

from server.registry import hands_tools
from server.services import hands_contract, hands_service, look_diff
from tests.server import test_hands_0153 as base

_case = base._case
isolated, hands, asks, in_turn, in_job = base.isolated, base.hands, base.asks, base.in_turn, base.in_job

pytestmark = pytest.mark.one_arslan

PIXELS = "c2NyZWVuc2hvdA" * 30
# The fixture window at (240, 417) points, 460×592, captured at 2 px per point.
CAPTURE = {"ok": True, "window_id": 85125, "title": "Hands Fixture", "onscreen": True,
           "frame": {"x": 240, "y": 417, "width": 460, "height": 592}, "scale": 2.0,
           "width": 920, "height": 1184, "mime": "image/jpeg", "data": PIXELS}


@pytest.fixture(autouse=True)
def fresh_memory():
    look_diff._last.clear()
    hands_tools._shot_notes_said.clear()
    yield
    look_diff._last.clear()
    hands_tools._shot_notes_said.clear()


def with_capture(hands, **changes):
    hands.capture = {"ok": True, "capture": {**CAPTURE, **changes}}


def with_bounds(hands):
    """The snapshot as agent-desktop answers it with --include-bounds: Save at (300, 500)."""
    real = hands.call

    async def call(op, args=None, **kw):
        reply = await real(op, args, **kw)
        if op == "snapshot":
            reply = copy.deepcopy(reply)
            save = reply["envelope"]["data"]["tree"]["children"][2]
            assert save["name"] == "Save"
            save["bounds"] = {"x": 300, "y": 500, "width": 80, "height": 30}
        return reply
    return call


async def look(**args):
    return await hands_tools.DesktopLookExecutor().execute({"app": "Notes", **args})


async def test_a_look_attaches_the_windows_screenshot_and_places_each_element(hands, asks, in_turn, monkeypatch):
    from server.services import hands_client
    with_capture(hands)
    monkeypatch.setattr(hands_client, "call", with_bounds(hands))
    result = await look()
    assert result["ok"] is True
    assert result["images"] == [{"mime_type": "image/jpeg", "data": PIXELS}]
    assert result["image_label"] == "Notes · Hands Fixture"
    assert "A screenshot of this window (920×1184 px) is attached" in result["text"]
    # Save's centre: ((300 + 40 - 240) * 2, (500 + 15 - 417) * 2) = (200, 196).
    assert 'button “Save” [@sfixture0:e3] (200, 196)' in result["text"]
    assert PIXELS not in result["text"]
    snapshot = next(a for op, a in hands.calls if op == "snapshot")
    assert snapshot["include_bounds"] is True
    capture = next(a for op, a in hands.calls if op == "capture_window")
    assert capture == {"app": "Notes", "window": "w-85125", "never": []}   # the window just read


async def test_the_trace_records_a_screenshot_was_taken_never_its_pixels(hands, asks, in_turn):
    with_capture(hands)
    await look()
    trace = hands_service.read_trace()
    assert trace[-1]["screenshot"] == "920x1184"
    assert PIXELS not in json.dumps(trace)


async def test_screenshots_off_means_no_capture_and_no_bounds(hands, asks, in_turn):
    hands_service.update_settings(screenshots=False)
    with_capture(hands)
    result = await look()
    assert "images" not in result
    assert hands.ops("capture_window") == []
    assert "include_bounds" not in next(a for op, a in hands.calls if op == "snapshot")


async def test_without_screen_recording_the_look_says_why_once_and_stands_on_its_text(hands, asks, in_turn):
    first = await look()                      # FakeHands refuses: screen_recording_off
    assert first["ok"] is True and "images" not in first
    assert "not allowed to record the screen" in first["text"]
    second = await look()
    assert second["ok"] is True and "record the screen" not in second["text"]


async def test_a_window_off_the_current_screen_is_said(hands, asks, in_turn):
    with_capture(hands, onscreen=False)
    result = await look()
    assert result["images"]
    assert "not on the current screen" in result["text"]


async def test_a_second_look_says_what_changed_and_a_third_that_nothing_did(hands, asks, in_turn, monkeypatch):
    from server.services import hands_client
    first = await look()
    assert "since your last look" not in first["text"]
    real = hands.call

    async def edited(op, args=None, **kw):
        reply = await real(op, args, **kw)
        if op == "snapshot":
            reply = copy.deepcopy(reply)
            tree = reply["envelope"]["data"]["tree"]
            tree["children"][4]["value"] = "Blue"                         # Color: Red → Blue
            tree["children"].append({"role": "sheet", "name": "Share"})   # a sheet appeared
        return reply
    monkeypatch.setattr(hands_client, "call", edited)
    second = await look()
    assert "Changed since your last look: + sheet “Share”; combobox “Color” is now “Blue”" in second["text"]
    third = await look()
    assert "Nothing changed since your last look." in third["text"]


async def test_a_look_into_a_part_is_not_compared(hands, asks, in_turn):
    await look()
    part = await look(ref="@sfixture0:e6")
    assert "since your last look" not in part["text"]


# ── pure pieces ──────────────────────────────────────────────────────────────

def test_a_password_value_never_enters_the_comparison():
    tree = {"role": "window", "name": "W", "children": [
        {"role": "textfield", "name": "Password", "value": "hunter2", "states": ["secure"]}]}
    assert "hunter2" not in json.dumps(list(look_diff.elements(tree).items()))


def test_same_named_siblings_stay_distinct_and_long_change_lists_are_counted():
    tree = {"role": "list", "children": [{"role": "row", "name": "x"}] * 3}
    assert len(look_diff.elements(tree)) == 4
    before = look_diff.elements({"role": "list", "children": []})
    after = look_diff.elements({"role": "list", "children": [{"role": "row", "name": f"r{i}"} for i in range(20)]})
    line = look_diff.describe(before, after)
    assert line.count("+ row") == look_diff.MAX_SHOWN and line.endswith("and 8 more")


def test_an_element_outside_the_screenshot_has_no_place():
    place = hands_contract.placer(CAPTURE)
    assert place({"x": 240, "y": 417, "width": 0, "height": 0}) == (0, 0)
    assert place({"x": 100, "y": 100, "width": 10, "height": 10}) is None      # left of the window
    assert place({"x": 700, "y": 500, "width": 10, "height": 10}) is None      # right of it
    assert hands_contract.placer({"frame": {}}) is None
