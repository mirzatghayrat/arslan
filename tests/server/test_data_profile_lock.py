import os
from pathlib import Path
import select
import subprocess
import sys

import pytest

from server.services.data_profile_lock import hold

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
