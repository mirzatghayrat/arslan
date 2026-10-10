"""Hands v2 P2-5 (spec 2026-10-08-0157 §15): what the release smoke on a real Mac found, held
here with Hands faked (the contract fixtures). Nothing is sent to a model."""
import asyncio
import itertools

import pytest

from server.registry import hands_tools
from server.services import hands_client
from tests.server import test_hands_0153 as base

isolated, hands, asks, in_job = base.isolated, base.hands, base.asks, base.in_job

pytestmark = pytest.mark.one_arslan

SHOT = {"ok": True, "capture": {"ok": True, "window_id": 85125, "title": "Groceries", "onscreen": True,
                                "frame": {"x": 0, "y": 0, "width": 10, "height": 10}, "scale": 1.0,
                                "width": 10, "height": 10, "mime": "image/jpeg", "data": "AAAA"}}


async def test_a_jobs_first_look_and_its_next_action_share_one_session(hands, asks, in_job, monkeypatch):
    """A look's snapshot and screenshot run at once; each used to start its own session, so the
    look's refs were in one and the action looked in the other (ref_unknown)."""
    hands.capture = SHOT
    real = hands.call
    numbers = itertools.count(1)

    async def slow_start(op, args=None, **kw):
        if op == "session_start":
            hands.calls.append((op, dict(args or {})))
            await asyncio.sleep(0.02)                 # Hands answers in its own time
            return {"ok": True, "session": f"run-{next(numbers)}"}
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", slow_start)
    await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
    await hands_tools.DesktopClickExecutor().execute({"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"})
    assert hands.ops("session_start") == ["session_start"]
    used = {a.get("session") for op, a in hands.calls if op in ("snapshot", "capture_window", "click")}
    assert used == {"run-1"}, used


async def test_an_app_list_hands_could_not_make_is_not_said_as_not_running(hands, asks, in_job, monkeypatch):
    """A stale macOS entry once made agent-desktop's list fail; Hands said "no apps", and every
    look answered "that app is not running" (P2-5 smoke, 2026-10-10)."""
    real = hands.call

    async def unreadable(op, args=None, **kw):
        if op == "list_apps":
            return {"ok": False, "refused": {"code": "apps_unreadable", "message": (
                "macOS did not give the list of running apps: inventory did not stabilize")}}
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", unreadable)
    result = await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
    assert result["ok"] is False and result["code"] == "apps_unreadable"
    assert "not running" not in result["error"] and "did not stabilize" in result["error"]
