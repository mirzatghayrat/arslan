import base64
import json
import os
from pathlib import Path
import select
import sqlite3
import subprocess
import sys
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

from server.crypto_material import keyring
from server.db.models import Base, MemoryStoreState, MemoryDeletion
from server.services import backup, profile_activation as activation
from server.services.data_profile_lock import activation_record_path, hold

SECRET = "synthetic-activation-only"


@pytest.fixture
def profiles(tmp_path):
    active, candidate = tmp_path / "active", tmp_path / "restored"
    active.mkdir()
    database = active / "arslan.db"
    engine = create_engine(f"sqlite:///{database}")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(MemoryStoreState.__table__.insert().values(
                id=1, instance_id=str(uuid4()), phase="active", deletion_epoch=0, digest_key="12" * 32))
            salt = bytes(range(16))
            connection.exec_driver_sql("INSERT INTO settings(key,value) VALUES (?,?)",
                                       ("crypto_salt_b64", base64.b64encode(salt).decode()))
            connection.exec_driver_sql("INSERT INTO settings(key,value) VALUES (?,?)",
                                       ("llm_api_key", keyring(SECRET, salt).encrypt(b"synthetic-key").decode()))
    finally:
        engine.dispose()
    (active / "original-marker").write_text("original profile")
    archive = tmp_path / "backup.zip"
    backup.create(active, archive)
    backup.restore(archive, candidate, current_db_path=database)
    (candidate / "candidate-marker").write_text("restored profile")
    return active, candidate, archive


@pytest.mark.parametrize("stop_after", [0, 1, 2, None])
def test_each_switch_boundary_rolls_back_without_losing_either_profile(profiles, monkeypatch, stop_after):
    active, candidate, archive = profiles
    original = (active / "arslan.db").read_bytes()
    archived = archive.read_bytes()
    original_inode = active.stat().st_ino
    candidate_inode = candidate.stat().st_ino
    move = activation._move
    written = activation._write_record
    count = 0

    def interrupted_move(source, destination):
        nonlocal count
        move(source, destination)
        count += 1
        if count == stop_after:
            raise RuntimeError("synthetic switch interruption")

    def interrupted_record(*args):
        written(*args)
        if stop_after == 0:
            raise RuntimeError("synthetic switch interruption")

    with monkeypatch.context() as patch:
        patch.setattr(activation, "_move", interrupted_move)
        patch.setattr(activation, "_write_record", interrupted_record)
        if stop_after is None:
            assert activation.switch_for_trial(active, candidate, SECRET)["status"] == "trial_pending"
        else:
            with pytest.raises(RuntimeError, match="synthetic switch interruption"):
                activation.switch_for_trial(active, candidate, SECRET)
    record = activation_record_path(active / "arslan.db")
    assert record.is_file() and record.stat().st_mode & 0o777 == 0o600
    if stop_after in (0, 1):
        operation = json.loads(record.read_bytes())["id"]
        with pytest.raises(ValueError, match="activation_paths_changed"):
            with activation.trial_ownership(active, operation, SECRET):
                pytest.fail("incomplete switch cannot enter a trial")
    with pytest.raises(ValueError, match="data_profile_recovery_required"):
        with hold(active / "arslan.db"):
            pytest.fail("pending switch must not boot")
    if stop_after == 1:
        assert not active.exists()  # Refused boot must not recreate it.
    assert activation.rollback(active) == {"rolled_back": True}
    assert activation.rollback(active) == {"rolled_back": False}
    assert active.stat().st_ino == original_inode
    assert candidate.stat().st_ino == candidate_inode
    assert (active / "arslan.db").read_bytes() == original
    assert (active / "original-marker").read_text() == "original profile"
    assert (candidate / "candidate-marker").read_text() == "restored profile"
    assert archive.read_bytes() == archived
    assert not record.exists()
    with hold(active / "arslan.db"):
        pass


def test_rollback_itself_can_be_interrupted_and_retried(profiles, monkeypatch):
    active, candidate, _ = profiles
    activation.switch_for_trial(active, candidate, SECRET)
    move = activation._move
    def interrupt(source, destination):
        move(source, destination)
        raise RuntimeError("synthetic rollback interruption")
    with monkeypatch.context() as patch:
        patch.setattr(activation, "_move", interrupt)
        with pytest.raises(RuntimeError, match="synthetic rollback interruption"):
            activation.rollback(active)
    assert not active.exists() and candidate.exists()
    assert activation.rollback(active)["rolled_back"]
    assert (active / "original-marker").exists()


@pytest.mark.parametrize("problem", ["key", "foreign", "unrestored", "busy"])
def test_preflight_refusal_never_moves_original(profiles, problem):
    active, candidate, _ = profiles
    from contextlib import nullcontext
    if problem == "foreign":
        with sqlite3.connect(candidate / "arslan.db") as db:
            db.execute("UPDATE memory_store_state SET instance_id=?", (str(uuid4()),))
    if problem == "unrestored":
        with sqlite3.connect(candidate / "arslan.db") as db:
            db.execute("DROP TABLE memory_restore_guard")
    original = (active / "arslan.db").read_bytes()
    with hold(active / "arslan.db") if problem == "busy" else nullcontext():
        with pytest.raises(ValueError):
            activation.switch_for_trial(active, candidate, "wrong" if problem == "key" else SECRET)
    assert (active / "arslan.db").read_bytes() == original
    assert (active / "original-marker").exists() and candidate.is_dir()
    assert not activation_record_path(active / "arslan.db").exists()


@pytest.mark.parametrize("problem", ["replace", "symlink", "corrupt_record", "record_mode", "traversal"])
def test_rollback_never_overwrites_unrecognized_paths(profiles, tmp_path, problem):
    active, candidate, _ = profiles
    activation.switch_for_trial(active, candidate, SECRET)
    record = activation_record_path(active / "arslan.db")
    before = record.read_bytes()
    if problem in ("replace", "symlink"):
        if problem == "replace":
            candidate.mkdir()
            (candidate / "unrelated").write_text("keep")
        else:
            candidate.symlink_to(tmp_path / "unrelated")
    elif problem == "corrupt_record":
        record.write_text("not-json")
    elif problem == "record_mode":
        record.chmod(0o644)
    else:
        value = json.loads(before)
        value["candidate"] = "../escape"
        record.write_text(json.dumps(value))
    with pytest.raises((ValueError, OSError)):
        activation.rollback(active)
    assert (active / "candidate-marker").exists()
    assert record.exists()
    if problem == "replace":
        assert (candidate / "unrelated").read_text() == "keep"


def test_switch_reconciles_deletion_records_advanced_after_restore(profiles):
    active, candidate, _ = profiles
    engine = create_engine(f"sqlite:///{active / 'arslan.db'}")
    try:
        with engine.begin() as connection:
            instance = connection.exec_driver_sql("SELECT instance_id FROM memory_store_state WHERE id=1").scalar()
            connection.execute(MemoryDeletion.__table__.insert().values(
                id=str(uuid4()), instance_id=instance, entry_id=str(uuid4()), epoch=1,
                content_digest="34" * 32, scope_kind="global", scope_key=""))
            connection.exec_driver_sql("UPDATE memory_store_state SET deletion_epoch=1 WHERE id=1")
    finally:
        engine.dispose()
    activation.switch_for_trial(active, candidate, SECRET)
    with sqlite3.connect(active / "arslan.db") as db:
        assert db.execute("SELECT deletion_epoch FROM memory_store_state WHERE id=1").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM memory_deletions").fetchone() == (1,)
    activation.rollback(active)


def test_abrupt_process_exit_after_first_move_can_be_rolled_back(profiles, tmp_path):
    active, candidate, _ = profiles
    original = (active / "arslan.db").read_bytes()
    code = ("import os, sys\nfrom pathlib import Path\n"
            "from server.services import profile_activation as activation\n"
            "move = activation._move\n"
            "def stop(source, destination):\n"
            " move(source, destination)\n"
            " os._exit(77)\n"
            "activation._move = stop\n"
            "activation.switch_for_trial(Path(sys.argv[1]), Path(sys.argv[2]), sys.stdin.read())\n")
    run = subprocess.run([sys.executable, "-c", code, str(active), str(candidate)],
                         input=SECRET, text=True, capture_output=True, timeout=15,
                         cwd=Path(__file__).resolve().parents[2],
                         env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)})
    assert run.returncode == 77 and not run.stdout and not run.stderr
    assert not active.exists()
    assert activation.rollback(active)["rolled_back"]
    assert (active / "arslan.db").read_bytes() == original
    assert (candidate / "candidate-marker").exists()


def test_trial_owns_exact_journal_and_excludes_normal_boot_rollback_and_second_trial(profiles):
    active, candidate, _ = profiles
    operation = activation.switch_for_trial(active, candidate, SECRET)["operation_id"]
    with activation.trial_ownership(active, operation, SECRET) as lease:
        assert lease == {"operation_id": operation, "status": "trial_owned"}
        for context in (hold(active / "arslan.db"), activation.trial_ownership(active, operation, SECRET)):
            with pytest.raises(ValueError, match="data_profile_in_use"):
                with context:
                    pytest.fail("trial owns the profile")
        with pytest.raises(ValueError, match="data_profile_in_use"):
            activation.rollback(active)
    # Lease exit is not approval/finalization. Normal boot remains blocked.
    with pytest.raises(ValueError, match="data_profile_recovery_required"):
        with hold(active / "arslan.db"):
            pytest.fail("journal still pending")
    assert activation.rollback(active)["rolled_back"]


@pytest.mark.parametrize("problem", ["wrong_operation", "wrong_secret", "missing_secret", "changed_layout"])
def test_trial_refusal_preserves_journal_and_both_profiles(profiles, problem):
    active, candidate, _ = profiles
    operation = activation.switch_for_trial(active, candidate, SECRET)["operation_id"]
    record = activation_record_path(active / "arslan.db")
    before = record.read_bytes()
    secret = SECRET
    if problem == "wrong_operation":
        operation = str(uuid4())
    elif problem == "wrong_secret":
        secret = "synthetic-wrong-secret"
    elif problem == "missing_secret":
        secret = None
    else:
        candidate.mkdir()
    with pytest.raises(ValueError):
        with activation.trial_ownership(active, operation, secret):
            pytest.fail("trial must be refused")
    assert record.read_bytes() == before
    assert (active / "candidate-marker").exists()
    if problem == "changed_layout":
        candidate.rmdir()
    assert activation.rollback(active)["rolled_back"]


def test_real_trial_process_holds_ownership_until_parent_pipe_closes(profiles, tmp_path):
    active, candidate, _ = profiles
    operation = activation.switch_for_trial(active, candidate, SECRET)["operation_id"]
    code = ("import json, sys\nfrom pathlib import Path\n"
            "from server.services.profile_activation import trial_ownership\n"
            "secret = json.loads(sys.stdin.readline())\n"
            "with trial_ownership(Path(sys.argv[1]), sys.argv[2], secret):\n"
            " print('TRIAL_OWNED', flush=True)\n"
            " sys.stdin.read()\n")
    process = subprocess.Popen([sys.executable, "-c", code, str(active), operation],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               cwd=Path(__file__).resolve().parents[2],
                               env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)})
    try:
        process.stdin.write((json.dumps(SECRET) + "\n").encode())
        process.stdin.flush()
        assert select.select([process.stdout], [], [], 10)[0]
        assert process.stdout.readline() == b"TRIAL_OWNED\n"
        with pytest.raises(ValueError, match="data_profile_in_use"):
            activation.rollback(active)
        process.stdin.close()
        process.wait(timeout=10)
        assert process.returncode == 0 and process.stderr.read() == b""
        assert activation.rollback(active)["rolled_back"]
    finally:
        if process.poll() is None:
            process.kill()  # Only the exact synthetic child created by this test.
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def _restricted_app(profiles, monkeypatch):
    from dataclasses import replace
    from server import config, crypto
    from server.activation_trial import create_app

    active, candidate, _ = profiles
    operation = activation.switch_for_trial(active, candidate, SECRET)["operation_id"]
    monkeypatch.setattr(config, "settings", replace(config.settings, secret_key=SECRET,
                                                   data_dir=active, db_path=str(active / "arslan.db")))
    # Restore process-global crypto state after this in-process test.
    monkeypatch.setattr(crypto, "_salt", crypto._salt)
    monkeypatch.setattr(crypto, "_salt_source", crypto._salt_source)
    return create_app(active, operation, "ab" * 32), active, operation


def test_restricted_trial_runs_storage_boot_but_exposes_only_authenticated_health(profiles, monkeypatch):
    from fastapi.testclient import TestClient
    import server.main as main
    from server.services import scheduler, evolution_watcher, curation_loop, fact_classify

    app, active, operation = _restricted_app(profiles, monkeypatch)
    def forbidden(*args, **kwargs):
        pytest.fail("restricted trial must not start the normal lifespan or background work")
    monkeypatch.setattr(main, "lifespan", forbidden)
    for module in (scheduler, evolution_watcher, curation_loop):
        monkeypatch.setattr(module, "start", forbidden)
    monkeypatch.setattr(fact_classify, "schedule", forbidden)
    with TestClient(app) as client:
        path = "/api/v1/activation-trial/health"
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
        response = client.get(path, headers={"Authorization": "Bearer " + "ab" * 32})
        assert response.json() == {"status": "ready", "mode": "activation_trial", "operation_id": operation}
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        for blocked in ("/docs", "/openapi.json", "/api/v1/settings", "/mcp-server", "/api/v1/memory/entries"):
            assert client.get(blocked).status_code == 404
            assert client.post(blocked, json={}).status_code == 404
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/arslan/synthetic"):
                pytest.fail("no websocket access")
        with pytest.raises(ValueError, match="data_profile_in_use"):
            activation.rollback(active)
        with sqlite3.connect(active / "arslan.db") as db:
            assert db.execute("SELECT applied FROM memory_restore_guard WHERE id=1").fetchone() == (1,)
    assert app.state.ready is False
    assert activation_record_path(active / "arslan.db").exists()
    assert activation.rollback(active)["rolled_back"]


def test_failed_trial_boot_never_reports_ready_and_releases_ownership(profiles, monkeypatch):
    from fastapi.testclient import TestClient
    from server import activation_trial

    app, active, _ = _restricted_app(profiles, monkeypatch)
    async def fail(engine):
        raise RuntimeError("synthetic boot failure")
    monkeypatch.setattr(activation_trial, "initialize", fail)
    with pytest.raises(RuntimeError, match="synthetic boot failure"):
        with TestClient(app):
            pytest.fail("failed startup must not serve health")
    assert app.state.ready is False
    assert activation.rollback(active)["rolled_back"]


def test_restricted_trial_checks_actual_key_at_startup_not_factory_time(profiles, monkeypatch):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from server import config

    app, active, _ = _restricted_app(profiles, monkeypatch)
    monkeypatch.setattr(config, "settings", replace(config.settings, secret_key="wrong-at-startup"))
    with pytest.raises(ValueError, match="activation_credentials_refused"):
        with TestClient(app):
            pytest.fail("changed key must not reach initialization")
    assert app.state.ready is False
    assert activation.rollback(active)["rolled_back"]


def test_trial_refuses_configuration_pointing_at_another_profile(profiles, monkeypatch, tmp_path):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from server import config

    app, active, _ = _restricted_app(profiles, monkeypatch)
    wrong = tmp_path / "unrelated-profile"
    monkeypatch.setattr(config, "settings", replace(config.settings, data_dir=wrong))
    with pytest.raises(ValueError, match="activation_trial_configuration_mismatch"):
        with TestClient(app):
            pytest.fail("must not read migration material from another profile")
    assert not wrong.exists()
    assert activation.rollback(active)["rolled_back"]


def test_trial_factory_does_not_bootstrap_configuration_in_fresh_process(tmp_path):
    home = tmp_path / "empty-home"
    home.mkdir()
    code = ("from pathlib import Path\nimport sys\n"
            "from server.activation_trial import create_app\n"
            "assert 'server.config' not in sys.modules\n"
            "try: create_app(Path(sys.argv[1]), 'unused', 'ab' * 32)\n"
            "except ValueError as error:\n"
            " assert str(error) == 'activation_trial_runtime_not_prepared'\n"
            "else: raise AssertionError('must require prepared runtime')\n"
            "assert 'server.config' not in sys.modules\n")
    run = subprocess.run([sys.executable, "-c", code, str(home / "absent")],
                         cwd=Path(__file__).resolve().parents[2], timeout=10, capture_output=True,
                         env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)})
    assert run.returncode == 0 and not run.stdout and not run.stderr
    assert not list(home.iterdir())


@pytest.mark.skipif(sys.platform != "darwin", reason="packaged macOS profile location")
def test_restricted_trial_over_real_loopback_http_then_rollback(profiles, tmp_path):
    import httpx

    active, candidate, _ = profiles
    home = tmp_path / "trial-home"
    home.mkdir()
    parent = home / "Library/Application Support"
    parent.mkdir(parents=True)
    active = active.rename(parent / "Arslan")
    candidate = candidate.rename(parent / "restored")
    operation = activation.switch_for_trial(active, candidate, SECRET)["operation_id"]
    repo = Path(__file__).resolve().parents[2]
    unrelated = home / "must-not-create"
    process = subprocess.Popen([sys.executable, str(repo / "packaging/server_entry.py"), "--activation-trial"],
                               cwd=repo,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
                                    "PYTHONPATH": str(repo), "ARSLAN_DATA_DIR": str(unrelated),
                                    "ARSLAN_DB_PATH": str(unrelated / "wrong.db"),
                                    "ARSLAN_SECRET_KEY": "inherited-wrong-key",
                                    "ARSLAN_SECRET_KEY_FILE": str(unrelated / "secret"), "ARSLAN_LIVE_LLM": "0"})
    try:
        process.stdin.write((json.dumps({"operation_id": operation, "access_token": "ab" * 32,
                                        "secret": SECRET}) + "\n").encode())
        process.stdin.flush()
        assert select.select([process.stdout], [], [], 10)[0]
        line = process.stdout.readline()
        assert line.startswith(b"ARSLAN_TRIAL_PORT=")
        port = int(line.split(b"=", 1)[1])
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=0.5, trust_env=False) as client:
            deadline = time.monotonic() + 15
            while True:
                try:
                    response = client.get("/api/v1/activation-trial/health",
                                          headers={"Authorization": "Bearer " + "ab" * 32})
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                assert process.poll() is None and time.monotonic() < deadline
                time.sleep(0.05)
            assert response.json() == {"status": "ready", "mode": "activation_trial", "operation_id": operation}
            assert client.get("/api/v1/activation-trial/health").status_code == 401
            assert client.post("/api/v1/memory/entries", json={}).status_code == 404
            assert client.get("/api/v1/settings").status_code == 404
            with pytest.raises(ValueError, match="data_profile_in_use"):
                activation.rollback(active)
        process.stdin.close()
        process.wait(timeout=10)
        assert process.returncode == 0
        assert activation_record_path(active / "arslan.db").exists()
        assert activation.rollback(active)["rolled_back"]
        assert not unrelated.exists() and not (home / ".arslan").exists()
        assert not (candidate / "api_token").exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
