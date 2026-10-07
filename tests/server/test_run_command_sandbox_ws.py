"""The chat window's side of leaving the sandbox (0.1.51 P3): a stopped command
gets a retry card; its checkbox means "for the rest of this conversation",
held in memory, never saved as a terminal rule."""
import pytest

import server.orchestrator.tool_loop as tool_loop_mod
from server.services import command_sandbox, terminal_exec
from tests.server.conftest import build_ws_client
from tests.server.test_run_command_confirm_flow import (
    _collect_until, _enable_shell, _stub_run_command_executor, _stub_tool_loop_adapter)


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal):
    return build_ws_client(portal, tmp_path, monkeypatch, db_name="sbx.db")


@pytest.fixture(autouse=True)
def fresh():
    command_sandbox._reset_for_tests()
    yield
    command_sandbox._reset_for_tests()


class _StopsInside:
    key = "run_command"

    def __init__(self):
        self.outside: list[bool] = []

    async def execute(self, args):
        out = terminal_exec.OUTSIDE_SANDBOX.get()
        self.outside.append(out)
        if not out:
            return {"ok": False, "exit_code": 1, "stdout": "", "stderr": "operation not permitted",
                    "sandbox": "workspace", "sandbox_denied": True, "note": "stopped"}
        return {"ok": True, "exit_code": 0, "stdout": "moved", "stderr": "", "sandbox": "off"}


def test_retry_card_runs_it_outside_and_the_checkbox_grants_this_conversation(app_client, monkeypatch):
    _enable_shell(app_client, policy="ask_risky")
    _stub_tool_loop_adapter(monkeypatch, "mv", ["~/Downloads/a.png", "~/Pictures/"])
    fake = _stub_run_command_executor(monkeypatch)
    stops = _StopsInside()
    tool_loop_mod.EXECUTORS["run_command"] = stops     # the patched dict both modules now share

    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.send_json({"type": "user_message", "content": "move my screenshot to Pictures"})
        card = _collect_until(ws, "propose_run_command")[-1]
        assert card["sandbox"] == "retry" and "rule" not in card
        ws.send_json({"type": "confirm_run_command", "call_id": card["call_id"], "remember": True})
        after = _collect_until(ws, "stream_end")
        results = [f for f in after if f.get("type") == "tool_result"]
        assert results and results[0]["ok"] is True

    assert stops.outside == [False, True]
    assert command_sandbox.granted("main") and not command_sandbox.granted("other")
    assert fake.calls == []

    # Never saved as a standing terminal rule.
    from server.services import terminal_policy

    async def rules():
        async with app_client.db_maker() as db:
            return await terminal_policy.always_allowed(db)
    assert app_client.portal.call(rules) == set()


def test_the_window_that_was_given_the_grant_runs_outside_from_the_start(app_client, monkeypatch):
    """The grant stays the chat window's own (jobs and unattended turns never use it)."""
    _enable_shell(app_client, policy="ask_risky")
    _stub_tool_loop_adapter(monkeypatch, "mv", ["~/Downloads/a.png", "~/Pictures/"])
    _stub_run_command_executor(monkeypatch)
    stops = _StopsInside()
    tool_loop_mod.EXECUTORS["run_command"] = stops
    command_sandbox.grant("main")
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.send_json({"type": "user_message", "content": "move my screenshot to Pictures"})
        frames = _collect_until(ws, "stream_end")
    assert "propose_run_command" not in [f["type"] for f in frames]
    assert stops.outside == [True]
