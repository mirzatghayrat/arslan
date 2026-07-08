"""code_sandbox (P1): the guards are the product — each one gets a test.

Tests preset the interpreter cache to the test venv's python so no batteries env is built.
"""
import sys

import pytest

from server.registry.executors import EXECUTORS, RunPythonExecutor
from server.services import code_sandbox

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _fast_env(monkeypatch):
    monkeypatch.setattr(code_sandbox, "_env_cache", (sys.executable, "test-env"))


async def test_happy_path_stdout():
    r = await code_sandbox.run_python("print(21 * 2)")
    assert r["ok"] is True and r["exit_code"] == 0
    assert "42" in r["stdout"]
    assert r["env_note"] == "test-env"


async def test_failing_script_surfaces_traceback():
    r = await code_sandbox.run_python("raise ValueError('boom')")
    assert r["ok"] is False and r["exit_code"] != 0
    assert "boom" in r["stderr"] and "boom" in r["error"]


async def test_timeout_kills_process_group():
    r = await code_sandbox.run_python("import time; time.sleep(60)", timeout_s=1.5)
    assert r["ok"] is False and "timed out" in r["error"]


async def test_env_is_scrubbed(monkeypatch):
    # The server process holds secrets; the child must never see them.
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "super-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-leak-me")
    r = await code_sandbox.run_python(
        "import os; print(sorted(k for k in os.environ if 'KEY' in k or 'SECRET' in k))"
    )
    assert r["ok"] is True
    assert "super-secret" not in r["stdout"] and "sk-leak-me" not in r["stdout"]
    assert "ARSLAN_SECRET_KEY" not in r["stdout"] and "OPENAI_API_KEY" not in r["stdout"]


async def test_output_truncated():
    r = await code_sandbox.run_python("print('x' * 100_000)")
    assert r["ok"] is True
    assert len(r["stdout"]) <= code_sandbox.MAX_OUTPUT_CHARS + 100
    assert "truncated" in r["stdout"]


async def test_created_files_listed():
    r = await code_sandbox.run_python(
        "open('result.csv', 'w').write('a,b\\n1,2\\n'); print('done')"
    )
    assert r["ok"] is True
    assert any(f.startswith("result.csv") for f in r["files"])


async def test_code_validation():
    assert (await code_sandbox.run_python(""))["ok"] is False
    assert "too large" in (await code_sandbox.run_python("x" * 200_000))["error"]


async def test_isolation_state_reported_honestly():
    # Whatever environment the suite runs in, the flag must be present and boolean —
    # never silently absent (the honesty contract: report isolation, don't assume it).
    r = await code_sandbox.run_python("print('hi')")
    assert isinstance(r.get("network_isolated"), bool)


# ── executor layer ─────────────────────────────────────────────────────────────

async def test_executor_registered_and_wraps_result():
    assert "run_python" in EXECUTORS
    out = await RunPythonExecutor().execute({"code": "print('ok')"})
    assert out["ok"] is True and out["external"] is False
    assert "ok" in out["stdout"] and "已执行 Python" in out["summary"]


async def test_executor_missing_code():
    out = await RunPythonExecutor().execute({})
    assert out["ok"] is False and "code" in out["error"]
