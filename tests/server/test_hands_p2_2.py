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
