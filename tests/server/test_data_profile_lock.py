import os
from pathlib import Path
import select
import subprocess
import sys

import pytest

from server.services.data_profile_lock import hold, lifecycle_path

pytestmark = pytest.mark.skipif(os.name != "posix", reason="packaged profile lock currently targets POSIX")


def test_same_profile_is_exclusive_but_other_profiles_are_independent(tmp_path):
    database = tmp_path / "one.db"
    with hold(database):
        with pytest.raises(ValueError, match="^data_profile_in_use$"):
            with hold(database):
                pytest.fail("cannot acquire twice")
        with hold(tmp_path / "two.db"):
            pass
    lock = tmp_path / ".one.db.arslan-lock"
    assert lock.is_file() and lock.stat().st_mode & 0o777 == 0o600
    assert lock.read_bytes() == b""
    with hold(database):
        pass  # An existing file alone is not a stale lock.


def test_exception_releases_os_ownership_without_unlinking(tmp_path):
    with pytest.raises(RuntimeError):
        with hold(tmp_path / "data.db"):
            raise RuntimeError("synthetic failure")
    before = (tmp_path / ".data.db.arslan-lock").stat().st_ino
    with hold(tmp_path / "data.db"):
        assert (tmp_path / ".data.db.arslan-lock").stat().st_ino == before


def test_profile_ownership_survives_directory_move(tmp_path):
    active = tmp_path / "active"
    active.mkdir()
    database = active / "arslan.db"
    database.write_bytes(b"synthetic original")
    previous = tmp_path / "previous"
    with hold(database):
        active.rename(previous)
        # A future activation coordinator installs a replacement at this path.
        active.mkdir()
        (active / "arslan.db").write_bytes(b"synthetic replacement")
        with pytest.raises(ValueError, match="^data_profile_in_use$"):
            with hold(database):
                pytest.fail("moved inner lock must not split profile ownership")
    assert (previous / "arslan.db").read_bytes() == b"synthetic original"
    assert database.read_bytes() == b"synthetic replacement"
    with hold(database):
        pass


def test_startup_cannot_recreate_absent_active_directory_during_move(tmp_path):
    active = tmp_path / "active"
    active.mkdir()
    database = active / "arslan.db"
    with hold(database):
        active.rename(tmp_path / "previous")
        with pytest.raises(ValueError, match="^data_profile_in_use$"):
            with hold(database):
                pytest.fail("must refuse before recreating the missing active path")
        assert not active.exists()
    with hold(database):
        assert active.is_dir()


@pytest.mark.parametrize("mode", ["symlink", "hardlink", "permissions", "fifo"])
def test_unsafe_lifecycle_lock_refuses_before_profile_creation(tmp_path, mode):
    database = tmp_path / "absent-profile" / "arslan.db"
    outer = lifecycle_path(database)
    victim = tmp_path / "unrelated"
    victim.write_bytes(b"synthetic unrelated file")
    if mode == "symlink":
        outer.symlink_to(victim)
    elif mode == "hardlink":
        os.link(victim, outer)
    elif mode == "fifo":
        os.mkfifo(outer, 0o600)
    else:
        outer.write_bytes(b"")
        outer.chmod(0o644)
    with pytest.raises((OSError, ValueError)):
        with hold(database):
            pytest.fail("unsafe lifecycle lock accepted")
    assert not database.parent.exists()
    assert victim.read_bytes() == b"synthetic unrelated file"


def test_legacy_inner_owner_is_respected_and_outer_lock_released_on_refusal(tmp_path):
    import fcntl

    database = tmp_path / "profile" / "arslan.db"
    database.parent.mkdir()
    inner = database.with_name(".arslan.db.arslan-lock")
    fd = os.open(inner, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="^data_profile_in_use$"):
            with hold(database):
                pytest.fail("older packaged owner must still exclude new startup")
        outer = lifecycle_path(database)
        outer_fd = os.open(outer, os.O_RDWR)
        try:
            fcntl.flock(outer_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert outer.stat().st_mode & 0o777 == 0o600
            assert outer.read_bytes() == b""
        finally:
            os.close(outer_fd)
    finally:
        os.close(fd)
    with hold(database):
        pass


@pytest.mark.parametrize("mode", ["symlink", "hardlink", "permissions", "fifo"])
def test_unsafe_lock_slot_is_refused_without_modifying_target(tmp_path, mode):
    lock = tmp_path / ".data.db.arslan-lock"
    victim = tmp_path / "unrelated"
    victim.write_bytes(b"Synthetic unrelated file")
    if mode == "symlink":
        lock.symlink_to(victim)
    elif mode == "hardlink":
        os.link(victim, lock)
    elif mode == "fifo":
        os.mkfifo(lock, 0o600)
    else:
        lock.write_bytes(b"")
        lock.chmod(0o644)
    with pytest.raises((OSError, ValueError)):
        with hold(tmp_path / "data.db"):
            pytest.fail("unsafe lock slot must not be accepted")
    assert victim.read_bytes() == b"Synthetic unrelated file"


def test_real_process_death_releases_lock_without_pid_guessing(tmp_path):
    database = tmp_path / "data.db"
    code = ("from pathlib import Path\nimport sys\n"
            "from server.services.data_profile_lock import hold\n"
            "with hold(Path(sys.argv[1])):\n"
            " print('locked', flush=True)\n"
            " sys.stdin.read()\n")
    process = subprocess.Popen([sys.executable, "-c", code, str(database)],
                               cwd=Path(__file__).resolve().parents[2],
                               env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path),
                                    "ARSLAN_SECRET_KEY_FILE": "", "ARSLAN_LIVE_LLM": "0"},
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert select.select([process.stdout], [], [], 5)[0], "child did not acquire lock"
        assert process.stdout.readline() == b"locked\n"
        with pytest.raises(ValueError, match="^data_profile_in_use$"):
            with hold(database):
                pytest.fail("other process owns the profile")
        process.kill()  # Only the exact synthetic child created by this test.
        process.wait(timeout=5)
        with hold(database):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def test_other_process_cannot_claim_profile_after_directory_move(tmp_path):
    active = tmp_path / "active"
    active.mkdir()
    database = active / "arslan.db"
    code = ("from pathlib import Path\nimport sys\n"
            "from server.services.data_profile_lock import hold\n"
            "try:\n"
            " with hold(Path(sys.argv[1])): print('unexpected owner')\n"
            "except ValueError as error:\n"
            " print(str(error))\n"
            " sys.exit(3)\n")
    with hold(database):
        active.rename(tmp_path / "previous")
        run = subprocess.run([sys.executable, "-c", code, str(database)],
                             cwd=Path(__file__).resolve().parents[2], timeout=10, capture_output=True,
                             env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)})
        assert run.returncode == 3 and run.stdout == b"data_profile_in_use\n"
        assert not active.exists()
