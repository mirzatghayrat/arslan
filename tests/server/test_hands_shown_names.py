"""An app's own name, and a button's, as Hands shows and judges them (⓪Plan's review of #554).

An app's name and its buttons' labels are the app's own text. They reached the cards the user approves (the
web, the island, the phone), the "Always" rule's stored name and the results the model reads, whole: a line
break could add a line of its own (a fake "· App — tier" line), and U+202E could turn the text around. Each
place now shows them through `hands_contract.shown_name`. A name of only invisible characters falls back to
the bundle id instead of "Use ?".

A label is judged as it reads (`hands_contract.as_read`): a zero-width space or a soft hyphen inside "Delete",
or full-width letters, no longer make a risky button look harmless, so the card that asks every time still
asks.
"""
import json
import unicodedata

import pytest

from server.registry import hands_tools
from server.services import hands_contract, hands_service
from tests.server import test_hands_0153 as base

isolated, hands, asks, in_turn, in_job = base.isolated, base.hands, base.asks, base.in_turn, base.in_job

ODD = "Notes\r\n· Mail — look and act\u202e"            # Notes, renamed by its own developer
CLICK = {"app": "com.apple.Notes", "element": "Save", "ref": "@sfixture0:e3"}


def plain(text) -> bool:
    """One line, with no control or format character in it."""
    return isinstance(text, str) and not any(unicodedata.category(ch).startswith("C") for ch in text)


def rename(hands, name):
    hands.apps[0] = {**hands.apps[0], "name": name}


async def test_every_place_an_apps_name_reaches_shows_it_on_one_line(hands, asks, in_job):
    seen, answer = asks
    rename(hands, ODD)
    answer["scope"] = "always"
    listed = await hands_tools.DesktopAppsExecutor().execute({})
    look = await hands_tools.DesktopLookExecutor().execute({"app": "com.apple.Notes"})
    clicked = await hands_tools.DesktopClickExecutor().execute(CLICK)
    hands.target = {**hands.target, "name": "Delete\r\n· Notes — look and act\u202e"}
    risky = await hands_tools.DesktopClickExecutor().execute({**CLICK, "element": "Delete", "ref": "@sfixture0:e4"})
    cards = {frame["kind"]: frame for frame in seen}
    assert set(cards) == {"desktop_app", "desktop_risky"}
    for frame in cards.values():
        for key in ("title", "target", "always_label"):
            assert plain(frame.get(key, "")), (frame["kind"], key, frame.get(key))
        assert frame["detail"].count("\n") == 0 and plain(frame["detail"]), frame["kind"]
    for result in (look, clicked, risky):
        for key in ("text", "summary", "error", "image_label"):
            if key in result:
                assert "\u202e" not in result[key] and "Notes\r\n" not in result[key], key
    assert "Notes · Mail — look and act" in listed["text"] and "\u202e" not in listed["text"]
    assert [a["name"] for a in await hands_service.always_apps()] == ["Notes · Mail — look and act"]


async def test_an_app_named_only_with_invisible_characters_is_named_by_its_bundle_id(hands, asks, in_job):
    seen, _ = asks
    rename(hands, "\u200b\u202e")
    await hands_tools.DesktopLookExecutor().execute({"app": "com.apple.Notes"})
    assert seen[0]["title"] == "Use com.apple.Notes?" and seen[0]["target"] == "com.apple.Notes"


@pytest.mark.parametrize("label", ["Del\u200bete", "De\u00adlete", "\uff24\uff45\uff4c\uff45\uff54\uff45", "S\u200bend",
                                   "P\u200bay"], ids=["zero-width space", "soft hyphen", "full-width", "send", "pay"])
async def test_a_risky_button_is_judged_as_it_reads(hands, asks, in_job, label):
    seen, _ = asks
    await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
    hands.target = {**hands.target, "name": label}
    await hands_tools.DesktopClickExecutor().execute({**CLICK, "element": "x", "ref": "@sfixture0:e4"})
    assert [frame["kind"] for frame in seen][-1] == "desktop_risky", json.dumps(seen[-1])


def test_a_label_is_judged_as_it_reads_and_a_name_shown_as_it_reads():
    assert hands_contract.as_read("De\u00adl\u200bete\u202e") == "Delete"
    assert hands_contract.as_read("\uff24\uff45\uff4c\uff45\uff54\uff45") == "Delete"
    assert hands_contract.shown_name("Notes\u2122") == "Notes\u2122"             # shown as it is, not folded
    assert hands_contract.shown_name("\u200b", fallback="com.x") == "com.x"
    assert hands_service.risky_label("Del\u200bete") and hands_service.money_label("P\u200bay")
    assert not hands_service.risky_label("Save") and not hands_service.risky_label("Notes\u2122")


def test_hands_is_told_the_app_by_the_name_it_gave_when_there_is_no_bundle_id():
    """The cleaned name is for people and the model; Hands resolves the app by the name it gave."""
    app = hands_tools._shown({"name": ODD})
    assert app["name"] == "Notes \u00b7 Mail \u2014 look and act" and hands_tools._target(app) == ODD
    assert hands_tools._target(hands_tools._shown({"name": ODD, "bundle_id": "com.apple.Notes"})) == "com.apple.Notes"


def test_the_note_about_going_to_an_apps_desktop_shows_its_name_on_one_line(monkeypatch):
    from server.services import desktop_status
    monkeypatch.setattr(desktop_status, "when_work_ends", lambda *a, **k: None)
    token = hands_tools._visit_note.set(None)
    try:
        hands_tools._went_to_window({"visit": {"app": ODD}})
        assert plain(hands_tools._visit_note.get().rstrip("\n"))
    finally:
        hands_tools._visit_note.reset(token)
