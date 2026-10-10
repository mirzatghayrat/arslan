"""run_command's offline mode (0.1.50): kernel-enforced no network, files still work."""
import socket
import sys

import pytest

from server.services import terminal_exec

macos = pytest.mark.skipif(sys.platform != "darwin" or terminal_exec.offline_wrapper() is None,
                           reason="seatbelt is macOS-only")

CONNECT = "python3 -c \"import socket,sys; socket.create_connection(('127.0.0.1', int(sys.argv[1])), 2)\" {port}"


@pytest.fixture
def listener():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    yield srv.getsockname()[1]
    srv.close()


@pytest.mark.macos
@macos
async def test_offline_blocks_network_but_writes_files(tmp_path, listener):
    out = await terminal_exec.run(CONNECT.format(port=listener) + " && echo connected", cwd=tmp_path, offline=True)
    assert out["ok"] is False and "connected" not in out["stdout"] and out["offline"] is True
    made = await terminal_exec.run("printf 'a,b\\n' > jobs.csv && cat jobs.csv", cwd=tmp_path, offline=True)
    assert made["ok"] is True and (tmp_path / "jobs.csv").read_text() == "a,b\n"


@pytest.mark.macos
@macos
async def test_normal_mode_keeps_the_network(tmp_path, listener):
    out = await terminal_exec.run(CONNECT.format(port=listener) + " && echo connected", cwd=tmp_path)
    assert out["ok"] is True and "connected" in out["stdout"] and "offline" not in out


async def test_offline_without_a_wrapper_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(terminal_exec, "offline_wrapper", lambda: None)
    out = await terminal_exec.run("echo hi", cwd=tmp_path, offline=True)
    assert out["ok"] is False and "cannot isolate the network" in out["error"]


async def test_the_executor_runs_offline_when_the_loop_says_so(tmp_path, monkeypatch):
    """The model never chooses: the flag is the loop's context variable."""
    from server.registry.executors import RunCommandExecutor
    from tests.server.test_workspace_tool_gate import _wire
    ws = tmp_path / "ws"
    ws.mkdir()
    engine = await _wire(tmp_path, monkeypatch, workspace=str(ws))
    seen = []

    async def fake_run(command, *, cwd, timeout_s, offline=False, sandbox=False, **kw):
        seen.append(offline)
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "cwd": str(cwd)}
    monkeypatch.setattr(terminal_exec, "run", fake_run)
    await RunCommandExecutor().execute({"command": "ls", "offline": False})
    token = terminal_exec.OFFLINE.set(True)
    try:
        await RunCommandExecutor().execute({"command": "ls", "offline": False})
    finally:
        terminal_exec.OFFLINE.reset(token)
    assert seen == [False, True]
    await engine.dispose()


def test_repeated_lines_fold_for_the_model_and_nothing_else_changes():
    """0.1.52 S2: runs of 3+ identical lines show once with a count; shorter runs,
    blank lines and different lines stay as they are."""
    text = "start\n" + "warning: x\n" * 50 + "a\na\nend\n\n\n\n"
    folded = terminal_exec.fold_repeats(text)
    assert folded.count("warning: x") == 1 and "repeated 49 more times" in folded
    assert "a\na\nend" in folded and folded.endswith("\n\n\n\n")
    assert terminal_exec.fold_repeats("one\ntwo\nthree") == "one\ntwo\nthree"


async def test_the_model_sees_folded_output(tmp_path):
    out = await terminal_exec.run("for i in $(seq 1 40); do echo same line; done; echo done", cwd=tmp_path)
    assert out["stdout"].count("same line") == 1 and "repeated 39 more times" in out["stdout"]
