"""PC-3: skill_script execution must FAIL CLOSED honestly rather than silently.

Part ① (Commit A): a non-.py entry, or a .py entry that DECLARES a network/CLI need
(`# requires: network` / `# requires: cli` front-matter marker), is rejected with an
explicit {ok:False, error:...} and the sandbox (code_sandbox.run_python) is NEVER invoked.
A clean .py entry (no marker) proceeds to run.
"""
import pytest

from server.registry.executors import RunPythonExecutor

pytestmark = pytest.mark.asyncio


@pytest.fixture
def skill_root(tmp_path, monkeypatch):
    """Point ARSLAN_DATA_DIR at a temp dir and return the skill_scripts/<key> dir factory."""
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))

    def _make(key: str):
        d = tmp_path / "skill_scripts" / key
        d.mkdir(parents=True, exist_ok=True)
        return d

    return _make


@pytest.fixture
def no_sandbox(monkeypatch):
    """Assert run_python is never called on the fail-closed paths."""
    from server.services import code_sandbox

    calls: list = []

    async def _boom(*a, **k):  # pragma: no cover - must never run on reject paths
        calls.append((a, k))
        return {"ok": True, "stdout": "", "sandboxed": True, "network_isolated": True}

    monkeypatch.setattr(code_sandbox, "run_python", _boom)
    return calls


async def test_non_py_entry_rejected_sandbox_not_invoked(skill_root, no_sandbox):
    d = skill_root("handoff")
    (d / "tool.sh").write_text("echo hi\n")
    out = await RunPythonExecutor().execute({"skill_script": "handoff/tool.sh"})
    assert out["ok"] is False and out["external"] is False
    assert ".sh" in out["error"] and "只支持 .py" in out["error"] and "未执行" in out["error"]
    assert no_sandbox == []  # sandbox never touched


async def test_network_marker_rejected_sandbox_not_invoked(skill_root, no_sandbox):
    d = skill_root("handoff")
    (d / "main.py").write_text("# requires: network\nimport json\nprint('x')\n")
    out = await RunPythonExecutor().execute({"skill_script": "handoff/main.py"})
    assert out["ok"] is False and out["external"] is False
    assert "网络" in out["error"] and "未执行" in out["error"]
    assert no_sandbox == []


async def test_cli_marker_rejected_sandbox_not_invoked(skill_root, no_sandbox):
    d = skill_root("handoff")
    (d / "main.py").write_text("#   requires:  cli\nprint('x')\n")
    out = await RunPythonExecutor().execute({"skill_script": "handoff/main.py"})
    assert out["ok"] is False and out["external"] is False
    assert "CLI" in out["error"] and "未执行" in out["error"]
    assert no_sandbox == []


async def test_clean_py_entry_proceeds_to_run(skill_root, monkeypatch):
    from server.services import code_sandbox

    seen: dict = {}

    async def _stub(code, **kwargs):
        seen["code"] = code
        seen["kwargs"] = kwargs
        return {"ok": True, "stdout": "42", "files": [],
                "sandboxed": True, "network_isolated": True, "env_note": "test"}

    monkeypatch.setattr(code_sandbox, "run_python", _stub)
    d = skill_root("handoff")
    (d / "helper.py").write_text("VALUE = 21\n")
    (d / "main_calc.py").write_text("from helper import VALUE\nprint(VALUE * 2)\n")
    out = await RunPythonExecutor().execute({"skill_script": "handoff/main_calc.py"})
    assert out["ok"] is True
    assert "VALUE * 2" in seen["code"]  # the entry code reached the sandbox
    assert seen["kwargs"]["extra_files"] == {"helper.py": "VALUE = 21\n"}
