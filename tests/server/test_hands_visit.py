"""Hands v2 §15 A18, the backend side: an app on another desktop is gone to (Hands decides, under the
user's borrow switch, which goes with every request that needs a window), the model is told, and the
visit comes back when the work that went there ends. desktop_open opens files and asks a running app
with no window for one, in the background. Hands is faked; nothing is sent to a model."""
import asyncio

import pytest

from server.registry import hands_tools
from server.services import desktop_status, hands_client, hands_service
from tests.server import test_hands_0153 as base

isolated, hands, asks, in_turn, in_job = base.isolated, base.hands, base.asks, base.in_turn, base.in_job

pytestmark = pytest.mark.one_arslan

VISIT = {"active": True, "app": "Notes", "since_s": 0, "last": None}


@pytest.fixture
def visiting(hands, monkeypatch):
    """Hands answers the first request that needs a window with "went to its desktop"."""
    real = hands.call
    state = {"first": True}

    async def call(op, args=None, **kw):
        reply = await real(op, args, **kw)
        if op in hands_tools._NEEDS_WINDOW and state["first"] and isinstance(reply, dict) and reply.get("ok"):
            state["first"] = False
            reply = {**reply, "visit_started": True, "visit": VISIT}
        return reply
    monkeypatch.setattr(hands_client, "call", call)
    return hands


async def test_a_look_that_went_to_another_desktop_says_so_and_comes_back_when_the_work_ends(visiting, asks, in_job):
    with desktop_status.working("c1", kind="job"):
        look = await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
        assert look["ok"] is True
        assert look["text"].startswith("Arslan went to the desktop where Notes's window is"), look["text"][:200]
        assert visiting.ops("visit_end") == [], "not while the work goes on"
    await asyncio.sleep(0)                                   # the scheduled call runs
    assert visiting.ops("visit_end") == ["visit_end"], "the work ended: come back"


async def test_an_action_on_a_visit_is_told_too(visiting, asks, in_job):
    with desktop_status.working("c1", kind="job"):
        click = await hands_tools.DesktopClickExecutor().execute(
            {"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"})
    assert "Arslan went to the desktop where Notes's window is" in click["text"], click["text"]


async def test_the_borrow_switch_goes_with_requests_that_need_a_window_only(hands, asks, in_job):
    await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
    sent = {op: a for op, a in hands.calls}
    assert sent["snapshot"]["borrow"] is True
    assert "borrow" not in sent["capture_window"], "a screenshot never goes anywhere"
    hands_service.update_settings(borrow=False)
    hands.calls.clear()
    await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
    assert {op: a for op, a in hands.calls}["snapshot"]["borrow"] is False


async def test_an_app_on_another_desktop_with_the_switch_off_is_said_plainly(hands, asks, in_job, monkeypatch):
    real = hands.call

    async def elsewhere(op, args=None, **kw):
        if op == "snapshot":
            hands.calls.append((op, dict(args or {})))
            return {"ok": False, "refused": {"code": "window_elsewhere",
                                             "message": "Notes's windows are on another desktop"}}
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", elsewhere)
    look = await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
    assert look["ok"] is False and look["code"] == "window_elsewhere"
    assert "on another desktop" in look["error"] and "borrow the front when needed" in look["error"]


@pytest.fixture
def opener(monkeypatch, hands):
    ran = []

    class Done:
        def __init__(self, code):
            self.code = code

        async def wait(self):
            return self.code

    async def exec_(*argv, **kw):
        ran.append(list(argv))
        name = argv[3]
        if not any(a["name"] == name for a in hands.apps):
            hands.apps.append({"name": name, "bundle_id": f"com.example.{name.lower()}", "tier": "full"})
        return Done(0)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", exec_)
    return ran


async def test_a_file_is_opened_in_its_app_in_the_background(hands, asks, in_job, opener, tmp_path):
    draft = tmp_path / "draft.txt"
    draft.write_text("hello\n")
    opened = await hands_tools.DesktopOpenExecutor().execute({"app": "TextEdit", "path": str(draft)})
    assert opened["ok"] and opened["outcome"] == "done", opened
    assert opener == [["/usr/bin/open", "-g", "-a", "TextEdit", str(draft)]]
    assert "Opened draft.txt in TextEdit in the background" in opened["text"]
    again = await hands_tools.DesktopOpenExecutor().execute({"app": "Notes", "path": str(draft)})
    assert again["outcome"] == "done", "a running app still opens the file"
    assert opener[-1] == ["/usr/bin/open", "-g", "-a", "Notes", str(draft)]
    missing = await hands_tools.DesktopOpenExecutor().execute({"app": "TextEdit", "path": str(tmp_path / "no.txt")})
    assert missing["code"] == "no_such_file" and len(opener) == 2


async def test_a_running_app_with_no_window_is_asked_for_one_and_one_elsewhere_is_left_there(hands, asks, in_job,
                                                                                              opener):
    hands.list_windows = {"ok": True, "app": hands.apps[0], "envelope": {"ok": True, "command": "list-windows",
                                                                          "data": []}}
    asked = await hands_tools.DesktopOpenExecutor().execute({"app": "Notes"})
    assert asked["ok"] and asked["outcome"] == "done", asked
    assert opener == [["/usr/bin/open", "-g", "-a", "Notes"]]
    assert "Asked Notes for a window" in asked["text"]
    assert [a.get("borrow") for op, a in hands.calls if op == "list_windows"] == [False], \
        "asking whether it has windows never goes to another desktop"

    hands.list_windows = {"ok": False, "refused": {"code": "window_elsewhere", "message": "elsewhere"}}
    there = await hands_tools.DesktopOpenExecutor().execute({"app": "Notes"})
    assert there["outcome"] == "no_effect" and "on another desktop" in there["text"]
    assert len(opener) == 1, "nothing opened again"

    hands.list_windows = None                                # the contract fixture: one window
    shown = await hands_tools.DesktopOpenExecutor().execute({"app": "Notes"})
    assert shown["outcome"] == "no_effect" and "already running with a window" in shown["text"]
    assert len(opener) == 1
