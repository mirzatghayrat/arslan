"""Durable generated files: ownership, byte fidelity, limits, no symlink export."""
import hashlib
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api import runs
from server.services import artifact_store, code_sandbox, execution_context


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_store, "root", lambda: tmp_path / "store")
    return tmp_path / "store"


def test_store_and_download_roundtrip(store):
    data = b"a,b\n1,2\n"
    artifact = artifact_store.store_bytes(7, "result.csv", data)
    assert artifact["sha256"] == hashlib.sha256(data).hexdigest()
    assert artifact_store.list_artifacts(7) == [artifact]
    assert artifact_store.list_artifacts(8) == []
    app = FastAPI()
    app.include_router(runs.router, prefix="/api/v1")
    client = TestClient(app)
    response = client.get(artifact["url"])
    assert response.status_code == 200 and response.content == data
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"
    assert "attachment" in response.headers["content-disposition"]
    assert client.get(artifact["url"].replace("/7/", "/8/")).status_code == 400


def test_workspace_links_inputs_and_limits_are_not_exported(store, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "main.py").write_text("input")
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    (workspace / "escape").symlink_to(outside)
    (workspace / "ok.csv").write_text("ok")
    (workspace / "large.bin").write_bytes(b"x" * 20)
    monkeypatch.setattr(artifact_store, "MAX_FILE_BYTES", 10)
    artifacts, warnings = artifact_store.export_workspace(5, workspace, excluded={"main.py"})
    assert [a["title"] for a in artifacts] == ["ok.csv"]
    assert len(warnings) == 2
    assert (store / artifacts[0]["filename"]).read_text() == "ok"


def test_download_rejects_symlink_and_manifest(store, tmp_path):
    store.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("private")
    (store / "run_5_bad.txt").symlink_to(outside)
    app = FastAPI()
    app.include_router(runs.router, prefix="/api/v1")
    client = TestClient(app)
    assert client.get("/api/v1/runs/5/artifacts/run_5_bad.txt").status_code == 404
    assert client.get("/api/v1/runs/5/artifacts/run_5_bad.manifest.json").status_code == 400


@pytest.mark.asyncio
@pytest.mark.macos
@pytest.mark.skipif(sys.platform != "darwin", reason="real Seatbelt execution")
async def test_real_python_output_survives_temporary_workspace_cleanup(store, monkeypatch):
    monkeypatch.setattr(code_sandbox, "_env_cache", (sys.executable, "test"))
    with execution_context.bind_run(91):
        result = await code_sandbox.run_python("open('result.csv', 'w').write('a,b\\n1,2\\n')")
    assert result["ok"], result
    artifact = result["artifacts"][0]
    assert artifact["run_id"] == 91
    assert (store / artifact["filename"]).read_text() == "a,b\n1,2\n"
    assert artifact_store.list_artifacts(91) == [artifact]
