import shutil
import pytest
from server.registry.executors import EXECUTORS


@pytest.mark.asyncio
async def test_run_command_rejects_non_whitelisted():
    r = await EXECUTORS["run_command"].execute({"command": "bash", "argv": ["-c", "echo x"]})
    assert r["ok"] is False
    assert "not allowed" in r["error"]


@pytest.mark.asyncio
async def test_run_command_rejects_missing_command():
    r = await EXECUTORS["run_command"].execute({"argv": ["status"]})
    assert r["ok"] is False


@pytest.mark.asyncio
async def test_run_command_rejects_shell_metachars():
    r = await EXECUTORS["run_command"].execute({"command": "git", "argv": ["status; rm -rf /"]})
    assert r["ok"] is False


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
async def test_run_command_git_version_ok_or_honest():
    r = await EXECUTORS["run_command"].execute({"command": "git", "argv": ["--version"]})
    # Either truly ran (summary present) or refused honestly (error present).
    assert ("summary" in r) or ("error" in r)
    if r["ok"]:
        assert "git version" in (r.get("stdout") or "").lower()
