"""Hands v2 §6.6 on the island: the window being worked on as a small thumbnail (memory only), and
what a borrow or takeover is doing, so the island can say it and offer its buttons. Hands faked."""
import base64
import io

import pytest
from PIL import Image

from server.api import desktop as desktop_api
from server.api import hands as hands_api
from server.registry import hands_tools
from server.services import desktop_status, hands_client
from tests.server import test_hands_0153 as base

isolated, hands, asks, in_turn, in_job = base.isolated, base.hands, base.asks, base.in_turn, base.in_job

pytestmark = pytest.mark.one_arslan


def jpeg(w=920, h=1184) -> str:
    out = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(out, format="JPEG")
    return base64.b64encode(out.getvalue()).decode()


@pytest.fixture(autouse=True)
def fresh_status():
    desktop_status._reset_for_tests()
    yield
    desktop_status._reset_for_tests()


def test_the_thumbnail_is_small_and_only_for_work_in_flight():
    desktop_status.note_thumb(jpeg())                          # nothing in flight: no-op
    with desktop_status.working("c1", title="do it", kind="job", job_id="j1"):
        desktop_status.note_thumb(jpeg())
        thumb = desktop_status.island_feed()["active"][0]["thumb"]
        with Image.open(io.BytesIO(base64.b64decode(thumb))) as image:
            assert max(image.size) <= desktop_status.THUMB_EDGE and image.format == "JPEG"
        desktop_status.note_thumb("not an image")
        assert desktop_status.island_feed()["active"][0]["thumb"] is None
    assert desktop_status.island_feed()["active"] == []


async def test_a_look_with_a_screenshot_gives_the_island_its_thumbnail(hands, asks, in_turn):
    hands.capture = {"ok": True, "capture": {"ok": True, "window_id": 85125, "title": "Hands Fixture",
                                             "onscreen": True, "frame": {"x": 0, "y": 0, "width": 460, "height": 592},
                                             "scale": 2.0, "width": 920, "height": 1184, "mime": "image/jpeg",
                                             "data": jpeg()}}
    with desktop_status.working("c1", title="look", kind="turn"):
        await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
        assert desktop_status.island_feed()["active"][0]["thumb"]


@pytest.mark.parametrize("reply, shown", [
    ({"ok": True, "borrow": "waiting", "takeover": {"active": False}}, {"borrow": "waiting", "takeover": None}),
    ({"ok": True, "borrow": None, "takeover": {"active": True, "paused": True, "remaining_s": 180}},
     {"borrow": None, "takeover": {"active": True, "paused": True, "remaining_s": 180}}),
    ({"ok": True, "borrow": None, "takeover": {"active": False}}, None),
    ({"ok": True, "borrow": "something else", "takeover": {}}, None),
])
async def test_the_island_learns_what_a_borrow_or_takeover_is_doing(monkeypatch, reply, shown):
    async def call(op, args=None, **kw):
        assert op == "activity_status"
        return reply
    monkeypatch.setattr(hands_client, "running", lambda: True)
    monkeypatch.setattr(hands_client, "call", call)
    assert await desktop_api._hands_activity() == shown


async def test_no_hands_no_hands_line(monkeypatch):
    monkeypatch.setattr(hands_client, "running", lambda: False)
    assert await desktop_api._hands_activity() is None


async def test_the_islands_now_and_skip_reach_hands(monkeypatch):
    sent = []

    async def call(op, args=None, **kw):
        sent.append(op)
        return {"ok": True}
    monkeypatch.setattr(hands_client, "call", call)
    assert (await hands_api.borrow_answer("now"))["ok"] is True
    assert (await hands_api.borrow_answer("skip"))["ok"] is True
    assert (await hands_api.borrow_answer("later"))["ok"] is False
    assert sent == ["borrow_now", "borrow_skip"]
