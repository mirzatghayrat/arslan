"""ASK1-b under the real seatbelt: a scheduled task's fire runs its command inside the sandbox, in Arslan's own folder.

The fire's signal is set (`command_gate.scheduled_fire`), nobody can be asked, and the real executor and the real
`terminal_exec.run` start the command. It writes in Arslan's own folder; a write beside that folder is refused by the
kernel. With the review's cut-back (`_FIRE_WRITES = False`) Arslan's own folder is refused too, and the command starts
in its run's temp folder. Stand-in file names only; every folder is the test's own.
"""
from __future__ import annotations

import sys

import pytest

from server.orchestrator import command_gate, tool_loop, untrusted
from server.orchestrator.turn_state import ToolTurn
from server.registry import executors
from server.services import command_sandbox, execution_context, permission_store

CID = "ask1b-seatbelt"
_REAL = executors.EXECUTORS["run_command"]
_MAC_ONLY = pytest.mark.skipif(sys.platform != "darwin", reason="seatbelt is macOS's")


@pytest.fixture
def own(execution_db, monkeypatch, tmp_path):
    permission_store._reset_for_tests()
    folder = tmp_path / "Arslan"
    folder.mkdir()
    monkeypatch.setenv("ARSLAN_DEFAULT_WORKSPACE", str(folder))
    monkeypatch.setitem(executors.EXECUTORS, "run_command", _REAL)
    return folder.resolve()


async def _fire(command: str) -> dict:
    trace: list = []

    async def tools():
        return [{"key": "run_command", "description": "run_command"}]
    with untrusted.carried(False), command_gate.scheduled_fire(CID):
        token = untrusted.track_turn()
        try:
            await tool_loop._run_tool("run_command", {"command": command}, "", ToolTurn(
                resolve_tools=tools, emit=lambda e: None, tool_timeout_s=60, tool_trace=trace, convo=[],
                conversation_id=CID))
        finally:
            untrusted.end_turn(token)
    [step] = trace
    return step["result"]


@pytest.mark.macos
@_MAC_ONLY
@pytest.mark.parametrize("writes", [True, False], ids=["writes", "cut back to read-only"])
async def test_a_fires_command_runs_inside_seatbelt(own, monkeypatch, writes):
    if not command_sandbox.available():
        pytest.skip("seatbelt can't start here (it can't nest inside another sandbox)")
    monkeypatch.setattr(command_gate, "_FIRE_WRITES", writes)
    command = f"echo in > {own}/zz-inside.txt; echo out > {own.parent}/zz-beside.txt; pwd"
    with execution_context.bind_run(987654):
        result = await _fire(command)
    assert result["sandbox"] == "workspace"                               # seatbelt wrapped it
    assert not (own.parent / "zz-beside.txt").exists()                     # the kernel refused the write beside it
    assert "Operation not permitted" in result["stderr"]
    if writes:
        assert result["cwd"] == str(own) and (own / "zz-inside.txt").read_text() == "in\n"
    else:
        assert result["cwd"] != str(own) and not (own / "zz-inside.txt").exists()
