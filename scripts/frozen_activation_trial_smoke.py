"""Synthetic frozen restore/control/trial/restart; source backup creation only."""
import argparse
import hashlib
import json
from pathlib import Path
import select
import subprocess
import tempfile
import time
from uuid import uuid4

import httpx

from scripts.frozen_sidecar_smoke import start, stop
from server.services import backup
from server.services.data_profile_lock import activation_record_path
from server.services.recovery_preflight import check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--finalize", action="store_true", help="Finalize disposable synthetic data only")
    parser.add_argument("--native-control-test", type=Path, help="Temporary Rust test executable for native transport")
    parser.add_argument("--native-trial", action="store_true", help="Also repeat trial through native launcher")
    args = parser.parse_args()
    if args.native_trial and not args.native_control_test:
        parser.error("--native-trial requires --native-control-test")
    binary = args.binary.resolve()
    assert binary.name == "arslan-server" and binary.is_file()
    assert binary.is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert any(part.startswith(("arslan-candidate-build.", "arslan-native-candidate.")) for part in binary.parts)
    native = args.native_control_test.resolve() if args.native_control_test else None
    if native:
        assert native.is_file() and native.name.startswith("arslan_desktop_lib-")
        assert native.is_relative_to(Path(tempfile.gettempdir()).resolve())
        assert any(part.startswith("arslan-native-candidate.") for part in native.parts)
    with tempfile.TemporaryDirectory(prefix="arslan-frozen-trial-") as folder:
        home = Path(folder)
        control_env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home),
                       "ARSLAN_DATA_DIR": str(home / "must-not-create"),
                       "ARSLAN_DB_PATH": str(home / "must-not-create-db"),
                       "ARSLAN_SECRET_KEY": "inherited-wrong-key",
                       "ARSLAN_SECRET_KEY_FILE": str(home / "must-not-create-key"),
                       "ARSLAN_LIVE_LLM": "0"}

        def control(payload, expected=0):
            if native:
                assert payload.get("candidate", "restored") == "restored"
                assert payload.get("secret", "frozen-smoke-synthetic-only") in ("frozen-smoke-synthetic-only", "wrong-key")
                environment = {**control_env, "ARSLAN_CONTROL_TEST_BINARY": str(binary),
                               "ARSLAN_CONTROL_TEST_ACTION": payload["action"],
                               "ARSLAN_CONTROL_TEST_OPERATION": payload.get("operation_id", "")}
                if payload.get("secret") == "wrong-key":
                    environment["ARSLAN_CONTROL_TEST_WRONG_KEY"] = "1"
                result = subprocess.run([str(native), "--ignored", "--exact",
                                         "recovery_control::tests::packaged_control_fixture", "--nocapture"],
                                        cwd=home, capture_output=True,
                                        timeout=110 if payload["action"] == "trial" else 35, env=environment)
                assert result.returncode == 0, "native control fixture failed"
                lines = [line.split(b"NATIVE_CONTROL_RESULT=", 1)[1] for line in result.stdout.splitlines()
                         if b"NATIVE_CONTROL_RESULT=" in line]
                assert len(lines) == 1
                message = json.loads(lines[0])
            else:
                result = subprocess.run([str(binary), "--activation-control"], cwd=home,
                                        input=(json.dumps(payload) + "\n").encode(), capture_output=True,
                                        timeout=30, env=control_env)
                assert result.returncode == expected, "unexpected activation control exit"
                message = json.loads(result.stdout)
            assert b"frozen-smoke-synthetic-only" not in result.stdout + result.stderr
            if expected:
                assert message == {"ok": False, "code": "activation_control_refused"}
            else:
                assert message["ok"] is True
            return message.get("result")

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
        if native:
            prepared = control({"action": "prepare", "archive": str(archive), "candidate": candidate.name})
            assert prepared["prepared"] and prepared["candidate"] == candidate.name
            assert not prepared["secret_included"] and prepared["files"] > 0
        else:
            restored = subprocess.run([str(binary), "--restore-offline", "--archive", str(archive),
                                       "--new-data-dir", str(candidate), "--current-db-path", str(active / "arslan.db")],
                                      cwd=home, capture_output=True, timeout=30, env=control_env)
            assert restored.returncode == 0 and json.loads(restored.stdout)["ok"] is True
        original = (active / "arslan.db").read_bytes()
        preflight = check(candidate / "arslan.db", "frozen-smoke-synthetic-only")
        assert preflight["status"] == "compatible", preflight
        control({"action": "switch", "candidate": candidate.name, "secret": "wrong-key"}, expected=1)
        assert (active / "arslan.db").read_bytes() == original
        operation = control({"action": "switch", "candidate": candidate.name,
                             "secret": "frozen-smoke-synthetic-only"})["operation_id"]
        assert control({"action": "inspect"}) == {"operation_id": operation}
        control({"action": "rollback", "operation_id": str(uuid4())}, expected=1)
        assert control({"action": "inspect"}) == {"operation_id": operation}
        finalization = {"action": "finalize", "operation_id": operation, "secret": "frozen-smoke-synthetic-only"}
        control(finalization, expected=1)  # No health receipt yet.
        # A normal fresh process must refuse BEFORE config can generate a key.
        refused = subprocess.run([str(binary)], cwd=home, input=b"", capture_output=True, timeout=15,
                                 env={"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home),
                                      "ARSLAN_LIVE_LLM": "0"})
        assert refused.returncode == 1
        assert refused.stdout == b"ARSLAN_ERROR=data_profile_recovery_required\n"
        assert not (home / ".arslan").exists()
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
                control(finalization, expected=1)  # Trial still owns the profile.
                control({"action": "rollback", "operation_id": operation}, expected=1)
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
        if args.native_trial:
            # A second trial invalidates the previous receipt; finalization must
            # therefore rely on the native launch/health/graceful-exit sequence.
            assert control({"action": "trial", "operation_id": operation}) == {"trial_completed": True}
        assert not (home / "must-not-create").exists()
        assert not (home / "must-not-create-key").exists()
        assert not (home / "must-not-create-db").exists()
        assert not (home / ".arslan").exists()
        if args.finalize:
            record = activation_record_path(active / "arslan.db")
            journal = json.loads(record.read_bytes())
            assert control(finalization) == {
                "finalized": True, "already_finalized": False, "original_retained": True,
            }
            assert not record.exists()
            assert (active.parent / journal["previous"] / "arslan.db").read_bytes() == original
        else:
            assert control({"action": "rollback", "operation_id": operation})["rolled_back"]
            assert control({"action": "inspect"}) == {"operation_id": None}
            assert (active / "arslan.db").read_bytes() == original
        process, client, _ = start(binary, home)
        try:
            settings = client.get("/api/v1/settings")
            assert settings.status_code == 200
            assert settings.json()["llm_api_key_status"] == "set"
        finally:
            client.close()
            assert stop(process) == 0
        if args.finalize:
            assert control(finalization) == {
                "finalized": True, "already_finalized": True, "original_retained": True,
            }
            assert (active.parent / journal["previous"] / "arslan.db").read_bytes() == original
    print(json.dumps({"frozen_activation_trial": "passed", "restricted_http": True,
                      "pipe_credentials": True, "wrong_inherited_key_ignored": True,
                      "normal_pending_boot_no_secret_generation": True,
                      "parent_pipe_shutdown": True, "normal_restart": True,
                      "packaged_coordination": "finalize" if args.finalize else "rollback",
                      "packaged_offline_restore": True, "source_backup_creation": True,
                      "native_control_transport": bool(native),
                      "native_trial_transport": args.native_trial,
                      "native_prepare_transport": bool(native),
                      "original_database_retained": True, "native_ui": False, "finalized": args.finalize,
                      "real_model": False, "installed_app": False,
                      "backend_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
