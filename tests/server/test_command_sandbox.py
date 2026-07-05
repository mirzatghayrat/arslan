import shutil
import pytest
from server.services import command_sandbox as cs


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
async def test_runs_git_version_in_tmpdir():
    r = await cs.run_command("git", ["--version"])
    # On macOS with sandbox-exec this truly runs; if seatbelt is unavailable it
    # refuses honestly. Accept either, but a run must report git's version.
    if r["ok"]:
        assert r["exit_code"] == 0
        assert "git version" in r["stdout"].lower()
    else:
        assert "sandbox" in r["error"].lower()


@pytest.mark.asyncio
async def test_refuses_when_seatbelt_unavailable(monkeypatch):
    monkeypatch.setattr(cs, "_seatbelt_wrapper", lambda *a, **k: None)  # now takes optional profile
    r = await cs.run_command("git", ["--version"])
    assert r["ok"] is False
    assert "sandbox" in r["error"].lower()


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
async def test_nonzero_exit_reported():
    r = await cs.run_command("git", ["not-a-real-subcommand-xyz"])
    # Either it ran and returned nonzero, or seatbelt refused. If it ran, ok is False.
    if "exit_code" in r and r["exit_code"] is not None:
        assert r["ok"] is False
        assert r["exit_code"] != 0


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
async def test_output_truncated(monkeypatch):
    monkeypatch.setattr(cs, "MAX_OUTPUT_CHARS", 10)
    r = await cs.run_command("git", ["--version"])
    if r["ok"]:
        assert len(r["stdout"]) <= 10 + 60  # 10 + truncation notice
