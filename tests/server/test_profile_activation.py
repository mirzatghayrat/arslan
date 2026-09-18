import base64
import json
import os
from pathlib import Path
import select
import sqlite3
import subprocess
import sys
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
