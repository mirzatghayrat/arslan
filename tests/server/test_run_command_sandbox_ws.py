"""The chat window's side of leaving the sandbox (0.1.51 P3): a stopped command goes back to the model, and the card
is its request to leave; that card's "In this conversation" is a stored grant of this conversation (S4a: `outside` / `*`),
never a terminal rule."""
import pytest

import server.orchestrator.tool_loop as tool_loop_mod
from server.services import command_sandbox, terminal_exec
from tests.server.conftest import build_ws_client
from tests.server.test_run_command_confirm_flow import (
    _collect_until, _enable_shell, _stub_run_command_executor, _stub_tool_loop_adapter, _ToolThenAnswerAdapter)


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal):
    return build_ws_client(portal, tmp_path, monkeypatch, db_name="sbx.db")


@pytest.fixture(autouse=True)
def fresh():
    command_sandbox._reset_for_tests()
    yield
    command_sandbox._reset_for_tests()


async def _grants(client):
    from sqlalchemy import select
    from server.db.models import PermissionGrant
    async with client.db_maker() as db:
        return [(g.conversation_id, g.task_id, g.kind, g.target)
                for g in (await db.execute(select(PermissionGrant))).scalars().all()]


async def _give(client):
    from server.services import permission_store
    async with client.db_maker() as db:
        await permission_store.add_grant(db, "main", "", "outside", "*", call_id="card-1")
        await db.commit()


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


class _StoppedThenAsksToLeave(_ToolThenAnswerAdapter):
    """The model runs a command, the sandbox stops it, and it comes back asking to leave, with its reason."""

    def __init__(self):
        super().__init__("mv", ["~/Downloads/a.png", "~/Pictures/"])
        self.saw_the_stop = False

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):  # noqa: ANN001
        from arslan.models import LLMResponse
        self._turn += 1
        self.saw_the_stop = self.saw_the_stop or "operation not permitted" in f"{user} {history}"
        if self._turn > 2:
            return LLMResponse(content="done", tool_calls=[], usage={})
        args = {"command": "mv ~/Downloads/a.png ~/Pictures/"}
        if self._turn == 2:
            args |= {"outside_sandbox": True, "why": "it moves a file out of the working folder"}
        return LLMResponse(content=None, usage={}, tool_calls=[{
            "id": f"c{self._turn}", "function": {"name": "run_command", "arguments": args}}])


def test_a_stop_shows_no_card_and_asking_to_leave_shows_one_with_the_models_reason(app_client, monkeypatch):
    # S2a-2 (R4): layer ③ runs with no card only where the sandbox can start; pinned so CI's Linux runs it too.
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    _enable_shell(app_client, policy="ask_risky")
    adapter = _StoppedThenAsksToLeave()
    monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: adapter)
    fake = _stub_run_command_executor(monkeypatch)
    stops = _StopsInside()
    tool_loop_mod.EXECUTORS["run_command"] = stops     # the patched dict both modules now share

    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.send_json({"type": "user_message", "content": "move my screenshot to Pictures"})
        frames = _collect_until(ws, "propose_run_command")
        card = frames[-1]
        assert [f["type"] for f in frames].count("propose_run_command") == 1
        assert [f["ok"] for f in frames if f.get("type") == "tool_result"] == [False]    # the stop, no card for it
        assert adapter.saw_the_stop
        assert card["sandbox"] == "outside" and "rule" not in card
        assert card["why"] == "it moves a file out of the working folder"
        assert card["perm_kind"] == "outside" and card["options"] == ["once", "conversation"]
        ws.send_json({"type": "confirm_run_command", "call_id": card["call_id"], "scope": "conversation"})
        after = _collect_until(ws, "stream_end")
        results = [f for f in after if f.get("type") == "tool_result"]
        assert results and results[0]["ok"] is True

    assert stops.outside == [False, True]
    assert app_client.portal.call(_grants, app_client) == [("main", "", "outside", "*")]
    assert fake.calls == []

    # Never saved as a standing terminal rule.
    from server.services import terminal_policy

    async def rules():
        async with app_client.db_maker() as db:
            return await terminal_policy.always_allowed(db)
    assert app_client.portal.call(rules) == set()


def test_the_window_that_was_given_the_grant_runs_outside_from_the_start(app_client, monkeypatch):
    """S4a: a stored grant, so a reload (a new socket) or a restart keeps it."""
    _enable_shell(app_client, policy="ask_risky")
    _stub_tool_loop_adapter(monkeypatch, "mv", ["~/Downloads/a.png", "~/Pictures/"])
    _stub_run_command_executor(monkeypatch)
    stops = _StopsInside()
    tool_loop_mod.EXECUTORS["run_command"] = stops
    app_client.portal.call(_give, app_client)
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.send_json({"type": "user_message", "content": "move my screenshot to Pictures"})
        frames = _collect_until(ws, "stream_end")
    assert "propose_run_command" not in [f["type"] for f in frames]
    assert stops.outside == [True]
