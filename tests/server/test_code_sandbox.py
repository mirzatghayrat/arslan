"""code_sandbox (P1): the guards are the product — each one gets a test.

Tests preset the interpreter cache to the test venv's python so no batteries env is built.
"""
import sys

import pytest

from server.registry.executors import EXECUTORS, RunPythonExecutor
from server.services import code_sandbox

pytestmark = pytest.mark.asyncio

# The happy-path tests below exercise a REAL, available sandbox backend, which v1 only
# ships on macOS (seatbelt). On Linux `run_python` is deliberately fail-closed (P0-1), so
# these would fail there — the correct Linux behavior (refusal) is asserted separately and
# UNconditionally by the refusal tests further down, which run on every platform incl. CI.
_NEEDS_REAL_SANDBOX = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="run_python happy-path needs a real sandbox backend (macOS seatbelt); "
    "Linux is fail-closed and covered by the refusal tests",
)


@pytest.fixture(autouse=True)
def _fast_env(monkeypatch):
    monkeypatch.setattr(code_sandbox, "_env_cache", (sys.executable, "test-env"))


@_NEEDS_REAL_SANDBOX
async def test_happy_path_stdout():
    r = await code_sandbox.run_python("print(21 * 2)")
    assert r["ok"] is True and r["exit_code"] == 0
    assert "42" in r["stdout"]
    assert r["env_note"] == "test-env"


@_NEEDS_REAL_SANDBOX
async def test_failing_script_surfaces_traceback():
    r = await code_sandbox.run_python("raise ValueError('boom')")
    assert r["ok"] is False and r["exit_code"] != 0
    assert "boom" in r["stderr"] and "boom" in r["error"]


@_NEEDS_REAL_SANDBOX
async def test_timeout_kills_process_group():
    r = await code_sandbox.run_python("import time; time.sleep(60)", timeout_s=1.5)
    assert r["ok"] is False and "timed out" in r["error"]


@_NEEDS_REAL_SANDBOX
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


@_NEEDS_REAL_SANDBOX
async def test_output_truncated():
    r = await code_sandbox.run_python("print('x' * 100_000)")
    assert r["ok"] is True
    assert len(r["stdout"]) <= code_sandbox.MAX_OUTPUT_CHARS + 100
    assert "truncated" in r["stdout"]


@_NEEDS_REAL_SANDBOX
async def test_created_files_listed():
    r = await code_sandbox.run_python(
        "open('result.csv', 'w').write('a,b\\n1,2\\n'); print('done')"
    )
    assert r["ok"] is True
    assert any(f.startswith("result.csv") for f in r["files"])


async def test_code_validation():
    assert (await code_sandbox.run_python(""))["ok"] is False
    assert "too large" in (await code_sandbox.run_python("x" * 200_000))["error"]


@_NEEDS_REAL_SANDBOX
async def test_isolation_state_reported_honestly():
    # Whatever environment the suite runs in, the flag must be present and boolean —
    # never silently absent (the honesty contract: report isolation, don't assume it).
    r = await code_sandbox.run_python("print('hi')")
    assert isinstance(r.get("network_isolated"), bool)


# ── executor layer ─────────────────────────────────────────────────────────────

@_NEEDS_REAL_SANDBOX
async def test_executor_registered_and_wraps_result():
    assert "run_python" in EXECUTORS
    out = await RunPythonExecutor().execute({"code": "print('ok')"})
    assert out["ok"] is True and out["external"] is False
    assert "ok" in out["stdout"] and "已执行 Python" in out["summary"]


async def test_executor_missing_code():
    out = await RunPythonExecutor().execute({})
    assert out["ok"] is False and "code" in out["error"]


# ── P0-1: fail-closed + visible escape valve ─────────────────────────────────────

async def test_backend_registry_selects_by_platform(monkeypatch):
    monkeypatch.setattr(code_sandbox.sys, "platform", "darwin")
    monkeypatch.setattr(code_sandbox.Path, "exists", lambda self: True)
    assert code_sandbox._select_backend().name == "seatbelt"
    monkeypatch.setattr(code_sandbox.sys, "platform", "linux")
    assert code_sandbox._select_backend().name == "null"


async def test_bubblewrap_backend_is_stub_unavailable():
    # Left as a stub this round — must report unavailable so Linux fails closed.
    assert code_sandbox.BubblewrapBackend().available() is False


async def test_unsandboxed_active_truth_table(monkeypatch):
    # darwin: seatbelt works → never unsandboxed, regardless of the valve.
    monkeypatch.setattr(code_sandbox.sys, "platform", "darwin")
    monkeypatch.setattr(code_sandbox.Path, "exists", lambda self: True)
    monkeypatch.setenv("ARSLAN_ALLOW_UNSANDBOXED_PY", "1")
    assert code_sandbox.unsandboxed_active() is False
    # non-darwin: unsandboxed ONLY when the valve is open.
    monkeypatch.setattr(code_sandbox.sys, "platform", "linux")
    assert code_sandbox.unsandboxed_active() is True
    monkeypatch.delenv("ARSLAN_ALLOW_UNSANDBOXED_PY", raising=False)
    assert code_sandbox.unsandboxed_active() is False


@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="asserts the REAL non-macOS fail-closed refusal; macOS ships a working seatbelt "
    "sandbox so run_python does not refuse there",
)
async def test_real_platform_fail_closed_when_no_sandbox(monkeypatch):
    # P0-1 security posture, guarded on the REAL platform (no monkeypatch): on any host
    # without an available backend (e.g. Linux CI), run_python must refuse fail-closed with
    # the valve OFF. This runs on Linux CI and actively defends the posture — the happy-path
    # tests skip there, so without this the refusal would go untested on the platform that
    # actually fails closed.
    monkeypatch.delenv("ARSLAN_ALLOW_UNSANDBOXED_PY", raising=False)
    assert code_sandbox._select_backend().available() is False   # real host, no backend
    r = await code_sandbox.run_python("print('must not run')")
    assert r["ok"] is False and r["sandboxed"] is False
    assert "exit_code" not in r                                   # refusal, not an execution
    assert "拒绝执行" in r["error"] and "ARSLAN_ALLOW_UNSANDBOXED_PY" in r["error"]


async def test_no_backend_valve_off_refuses_without_running(monkeypatch):
    # Non-darwin + valve OFF → refuse, and NEVER spawn a subprocess.
    monkeypatch.setattr(code_sandbox.sys, "platform", "linux")
    monkeypatch.delenv("ARSLAN_ALLOW_UNSANDBOXED_PY", raising=False)

    async def _boom(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("subprocess must NOT be spawned when the sandbox is unavailable")

    monkeypatch.setattr(code_sandbox.asyncio, "create_subprocess_exec", _boom)
    r = await code_sandbox.run_python("print('should not run')")
    assert r["ok"] is False and r["sandboxed"] is False
    assert "拒绝执行" in r["error"] and "ARSLAN_ALLOW_UNSANDBOXED_PY" in r["error"]


async def test_no_backend_valve_on_runs_unsandboxed_with_banner(monkeypatch, caplog):
    monkeypatch.setattr(code_sandbox.sys, "platform", "linux")
    monkeypatch.setenv("ARSLAN_ALLOW_UNSANDBOXED_PY", "1")
    with caplog.at_level("WARNING"):
        r = await code_sandbox.run_python("print('valve open')")
    assert r["ok"] is True and r["sandboxed"] is False
    assert "valve open" in r["stdout"]
    assert any("UNSANDBOXED run_python" in rec.message for rec in caplog.records)


async def test_darwin_path_reports_sandboxed_true(monkeypatch):
    # When a backend IS available the result carries sandboxed=True (env preset skips seatbelt
    # wrapping via a stub backend so the test runs on any host).
    class _Avail(code_sandbox.SandboxBackend):
        name = "test-avail"

        def available(self):
            return True

        def wrapper(self, profile=None):
            return None  # no real wrapper needed for the flag assertion

    monkeypatch.setattr(code_sandbox, "_select_backend", lambda: _Avail())
    r = await code_sandbox.run_python("print('ok')")
    assert r["ok"] is True and r["sandboxed"] is True


async def test_executor_propagates_sandboxed(monkeypatch):
    # The `sandboxed` field must survive the executor so it reaches the run trace / RunStep.
    monkeypatch.setattr(code_sandbox.sys, "platform", "linux")
    monkeypatch.setenv("ARSLAN_ALLOW_UNSANDBOXED_PY", "1")
    out = await RunPythonExecutor().execute({"code": "print('trace me')"})
    assert out["ok"] is True and out["sandboxed"] is False
    # Refused runs expose it too (valve off).
    monkeypatch.delenv("ARSLAN_ALLOW_UNSANDBOXED_PY", raising=False)
    refused = await RunPythonExecutor().execute({"code": "print('nope')"})
    assert refused["ok"] is False and refused["sandboxed"] is False
