"""Integration tests for the WS run_command confirmation flow (Task 6).

Drives the /ws/arslan endpoint end-to-end: a plain user_message routes to
_handle_answer, whose tool_loop emits ONE run_command tool call. The scoped
receive-router in ws/arslan.py pauses the loop on the injected confirm_command
callback, emits a propose_run_command frame, and awaits an inbound
confirm/cancel frame before executing (or declining).

Harness modeled on tests/server/test_ws_arslan.py: fresh sqlite DB per test,
stubbed adapters, TestClient websocket.
"""
import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
import server.orchestrator.arslan as arslan_mod
import server.orchestrator.router as router_mod
import server.orchestrator.tool_loop as tool_loop_mod
import server.registry.executors as executors_mod
from server.db.models import Base


# --------------------------------------------------------------------------- #
# Fake adapters
# --------------------------------------------------------------------------- #

class _ToolThenAnswerAdapter:
    """execute-role adapter for tool_loop: on the FIRST chat_stream turn yields a
    run_command tool-call JSON; on every subsequent turn yields a plain final answer
    (so the loop terminates after the tool result comes back)."""

    def __init__(self, command: str, argv: list[str], answer: str = "done"):
        self._tool_json = (
            '{"tool": "run_command", "args": {"command": "%s", "argv": %s}}'
            % (command, _json_argv(argv))
        )
        self._answer = answer
        self._turn = 0

    async def chat_stream(self, system, user, history=None):  # noqa: ANN001
        self._turn += 1
        if self._turn == 1:
            yield self._tool_json
        else:
            yield self._answer


def _json_argv(argv: list[str]) -> str:
    import json
    return json.dumps(argv)


class _FakeRunCommandExecutor:
    """Stand-in for RunCommandExecutor.execute — never touches the real sandbox."""

    key = "run_command"

    def __init__(self, result: dict | None = None):
        self.result = result or {"ok": True, "summary": "ran", "stdout": "x"}
        self.calls: list[dict] = []

    async def execute(self, args: dict) -> dict:
        self.calls.append(args)
        return dict(self.result)


# --------------------------------------------------------------------------- #
# Fixture: fresh DB + app client
# --------------------------------------------------------------------------- #

@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    import importlib

    import server.config as config

    importlib.reload(config)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'rc.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    return TestClient(create_app())


def _enable_shell(policy: str | None = None) -> None:
    """Enable the orchestrator shell (and optionally set the confirm policy)."""
    from server.services import settings_service

    data = {"orchestrator_shell_enabled": "true"}
    if policy is not None:
        data["shell_confirm_policy"] = policy

    async def _do():
        async with db_session.AsyncSessionLocal() as db:
            await settings_service.update_settings(db, data)

    anyio.run(_do)


def _stub_answer_route(monkeypatch) -> None:
    """Force the router to 'answer' so handle_user_message reaches _handle_answer
    (which wires confirm_command into tool_loop). Avoids a real router LLM call."""
    async def _fake_route(conversation_id, user_message):  # noqa: ANN001
        return router_mod.RouterResult(action="answer", reason="test")

    monkeypatch.setattr(arslan_mod.router, "route", _fake_route)


def _stub_tool_loop_adapter(monkeypatch, command: str, argv: list[str]) -> None:
    adapter = _ToolThenAnswerAdapter(command, argv)
    monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: adapter)


def _stub_run_command_executor(monkeypatch, result: dict | None = None) -> _FakeRunCommandExecutor:
    fake = _FakeRunCommandExecutor(result)
    # EXECUTORS is the dict resolve_executor consults for run_command.
    patched = dict(executors_mod.EXECUTORS)
    patched["run_command"] = fake
    monkeypatch.setattr(executors_mod, "EXECUTORS", patched)
    # tool_loop imported EXECUTORS by name; patch that binding too so the
    # `"run_command" in EXECUTORS` / resolve path both see the fake.
    monkeypatch.setattr(tool_loop_mod, "EXECUTORS", patched)
    return fake


def _collect_until(ws, want_type: str, max_frames: int = 40) -> list[dict]:
    """Drain frames until one of `want_type` is seen (inclusive)."""
    frames: list[dict] = []
    for _ in range(max_frames):
        f = ws.receive_json()
        frames.append(f)
        if f.get("type") == want_type:
            break
    return frames


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_confirm_run_command_executes(app_client, monkeypatch):
    _enable_shell()
    _stub_answer_route(monkeypatch)
    _stub_tool_loop_adapter(monkeypatch, "git", ["status"])
    fake_exec = _stub_run_command_executor(monkeypatch)

    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "user_message", "content": "check the repo"})

        frames = _collect_until(ws, "propose_run_command")
        propose = frames[-1]
        assert propose["type"] == "propose_run_command"
        assert propose["command"] == "git"
        assert propose["argv"] == ["status"]
        assert propose["pretty"] == "git status"
        call_id = propose["call_id"]

        # Approve → the executor runs, tool_result ok True, then the answer streams.
        ws.send_json({"type": "confirm_run_command", "call_id": call_id})
        after = _collect_until(ws, "stream_end")
        tool_results = [f for f in after if f.get("type") == "tool_result"]
        assert tool_results, f"expected a tool_result frame in {[f['type'] for f in after]}"
        assert tool_results[0]["ok"] is True

    assert len(fake_exec.calls) == 1
    assert fake_exec.calls[0]["command"] == "git"


def test_cancel_run_command_declines(app_client, monkeypatch):
    _enable_shell()
    _stub_answer_route(monkeypatch)
    _stub_tool_loop_adapter(monkeypatch, "git", ["status"])
    fake_exec = _stub_run_command_executor(monkeypatch)

    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "user_message", "content": "check the repo"})

        frames = _collect_until(ws, "propose_run_command")
        call_id = frames[-1]["call_id"]

        # Cancel → executor never runs; tool_result ok False (declined); Arslan still answers.
        ws.send_json({"type": "cancel_run_command", "call_id": call_id})
        after = _collect_until(ws, "stream_end")
        tool_results = [f for f in after if f.get("type") == "tool_result"]
        assert tool_results, f"expected a tool_result frame in {[f['type'] for f in after]}"
        assert tool_results[0]["ok"] is False
        assert any(f.get("type") == "stream_end" for f in after)

    assert len(fake_exec.calls) == 0  # never executed


def test_ask_risky_auto_runs_low_no_card(app_client, monkeypatch):
    _enable_shell(policy="ask_risky")
    _stub_answer_route(monkeypatch)
    _stub_tool_loop_adapter(monkeypatch, "git", ["status"])  # LOW risk
    fake_exec = _stub_run_command_executor(monkeypatch)

    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "user_message", "content": "check the repo"})

        after = _collect_until(ws, "stream_end")
        types = [f["type"] for f in after]
        assert "propose_run_command" not in types, f"LOW+ask_risky must not prompt: {types}"
        tool_results = [f for f in after if f.get("type") == "tool_result"]
        assert tool_results and tool_results[0]["ok"] is True

    assert len(fake_exec.calls) == 1


def test_ask_risky_still_cards_medium(app_client, monkeypatch):
    _enable_shell(policy="ask_risky")
    _stub_answer_route(monkeypatch)
    _stub_tool_loop_adapter(monkeypatch, "git", ["commit", "-m", "x"])  # MEDIUM risk
    fake_exec = _stub_run_command_executor(monkeypatch)

    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "user_message", "content": "commit please"})

        frames = _collect_until(ws, "propose_run_command")
        assert frames[-1]["type"] == "propose_run_command", "MEDIUM must still prompt"
        call_id = frames[-1]["call_id"]
        ws.send_json({"type": "confirm_run_command", "call_id": call_id})
        after = _collect_until(ws, "stream_end")
        assert any(f.get("type") == "tool_result" for f in after)

    assert len(fake_exec.calls) == 1


def test_remember_auto_approves_same_shape(app_client, monkeypatch):
    _enable_shell()  # ask_all default → both would normally card
    _stub_answer_route(monkeypatch)
    fake_exec = _stub_run_command_executor(monkeypatch)

    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update

        # Turn 1: git status, confirm with remember=true.
        _stub_tool_loop_adapter(monkeypatch, "git", ["status"])
        ws.send_json({"type": "user_message", "content": "check repo"})
        frames = _collect_until(ws, "propose_run_command")
        call_id = frames[-1]["call_id"]
        ws.send_json({"type": "confirm_run_command", "call_id": call_id, "remember": True})
        after1 = _collect_until(ws, "stream_end")
        assert any(f.get("type") == "tool_result" for f in after1)

        # Turn 2: same-shape command (git status) → auto-approved, NO new card.
        _stub_tool_loop_adapter(monkeypatch, "git", ["status"])
        ws.send_json({"type": "user_message", "content": "check repo again"})
        after2 = _collect_until(ws, "stream_end")
        types2 = [f["type"] for f in after2]
        assert "propose_run_command" not in types2, f"remembered shape must auto-run: {types2}"
        assert any(f.get("type") == "tool_result" and f.get("ok") for f in after2)

    assert len(fake_exec.calls) == 2
