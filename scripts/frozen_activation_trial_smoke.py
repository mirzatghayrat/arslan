"""Synthetic frozen normal boot -> source switch -> frozen trial -> rollback."""
import hashlib
import json
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time

import httpx

from scripts.frozen_sidecar_smoke import start, stop
from server.services import backup, profile_activation
from server.services.recovery_preflight import check


def main():
    binary = Path(sys.argv[1]).resolve()
    assert binary.name == "arslan-server" and binary.is_file()
    assert binary.is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert any(part.startswith(("arslan-candidate-build.", "arslan-native-candidate.")) for part in binary.parts)
    with tempfile.TemporaryDirectory(prefix="arslan-frozen-trial-") as folder:
        home = Path(folder)
        process, client, _ = start(binary, home)
        try:
            assert client.put("/api/v1/settings", json={"llm_api_key": "synthetic-trial-provider-key"}).status_code == 200
        finally:
            client.close()
            assert stop(process) == 0
        active = home / "Library/Application Support/Arslan"
        candidate = active.with_name("restored")
        archive = home / "backup.zip"
        backup.create(active, archive)
        backup.restore(archive, candidate, current_db_path=active / "arslan.db")
        original = (active / "arslan.db").read_bytes()
        preflight = check(candidate / "arslan.db", "frozen-smoke-synthetic-only")
        assert preflight["status"] == "compatible", preflight
        operation = profile_activation.switch_for_trial(active, candidate, "frozen-smoke-synthetic-only")["operation_id"]
        token = "ab" * 32
        child = subprocess.Popen([str(binary), "--activation-trial"], cwd=home,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env={"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home),
                                      "ARSLAN_DATA_DIR": str(home / "must-not-create"),
                                      "ARSLAN_SECRET_KEY": "inherited-wrong-key",
                                      "ARSLAN_SECRET_KEY_FILE": str(home / "must-not-create-key"),
                                      "ARSLAN_LIVE_LLM": "0"})
        try:
            child.stdin.write((json.dumps({"operation_id": operation, "access_token": token,
                                            "secret": "frozen-smoke-synthetic-only"}) + "\n").encode())
            child.stdin.flush()
            assert select.select([child.stdout], [], [], 15)[0]
            line = child.stdout.readline()
            assert line.startswith(b"ARSLAN_TRIAL_PORT="), "missing restricted trial handshake"
            port = int(line.split(b"=", 1)[1])
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=0.5, trust_env=False) as probe:
                deadline = time.monotonic() + 20
                while True:
                    try:
                        response = probe.get("/api/v1/activation-trial/health",
                                             headers={"Authorization": f"Bearer {token}"})
                        if response.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    assert child.poll() is None and time.monotonic() < deadline
                    time.sleep(0.05)
                assert response.json() == {"status": "ready", "mode": "activation_trial", "operation_id": operation}
                assert probe.get("/api/v1/activation-trial/health").status_code == 401
                assert probe.get("/api/v1/settings").status_code == 404
                assert probe.post("/api/v1/memory/entries", json={}).status_code == 404
            child.stdin.close()
            child.wait(timeout=10)
            assert child.returncode == 0
            output = child.stdout.read() + child.stderr.read()
            assert token.encode() not in output and b"frozen-smoke-synthetic-only" not in output
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()
        assert not (home / "must-not-create").exists()
        assert not (home / "must-not-create-key").exists()
        assert not (home / ".arslan").exists()
        assert profile_activation.rollback(active)["rolled_back"]
        assert (active / "arslan.db").read_bytes() == original
        process, client, _ = start(binary, home)
        try:
            settings = client.get("/api/v1/settings")
            assert settings.status_code == 200
            assert settings.json()["llm_api_key_status"] == "set"
        finally:
            client.close()
            assert stop(process) == 0
    print(json.dumps({"frozen_activation_trial": "passed", "restricted_http": True,
                      "pipe_credentials": True, "wrong_inherited_key_ignored": True,
                      "parent_pipe_shutdown": True, "source_rollback_and_normal_restart": True,
                      "original_database_retained": True, "native_ui": False, "finalized": False,
                      "real_model": False, "installed_app": False,
                      "backend_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
