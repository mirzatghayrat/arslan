"""SBX-1 (v0.1.64): the exact text of every seatbelt profile Arslan writes, for fixed inputs.

The texts were recorded from main before SBX-1 moved the profiles onto `sandbox_profile`, and
this file passes on both. Later SBX PRs that change a profile change its text here, so the
change is visible line by line in review. Paths under the test's folder are written as <T>.
"""
import os
from pathlib import Path

import pytest

from server.services import capability_sandbox, code_sandbox, command_sandbox, ssh_exec


@pytest.fixture
def T(tmp_path):
    """The test's folder, with the files, folders and a link the profiles below are given."""
    for folder in ("ws", "closed/ws", "closed/proj", "other", "prot", "data", "granted", "runtimes", "mcp",
                   "work", "refs", "py/bin", "py/lib", "venv/bin", "venv/lib"):
        (tmp_path / folder).mkdir(parents=True)
    for file in ("notes.txt", "prot.key", "updater.key", "copy.txt", "py/bin/python3"):
        (tmp_path / file).write_text("x")
    (tmp_path / "link").symlink_to(tmp_path / "ws")
    (tmp_path / "link-granted").symlink_to(tmp_path / "granted")
    (tmp_path / "venv/bin/python").symlink_to(tmp_path / "py/bin/python3")
    return tmp_path


def _shown(text: str, T: Path) -> str:
    return text.replace(os.path.realpath(T), "<T>")


def test_commands_profile_with_every_part(T):
    text = command_sandbox.profile(
        [T / "link", T / "notes.txt", T / "missing", T / "closed/ws"], [T / "prot", T / "prot.key"], offline=True,
        closed=[T / "closed"], readable=[T / "closed/proj", T / "other", T / "closed/ws"], copies=[T / "copy.txt"])
    assert _shown(text, T) == """\
(version 1)
(allow default)
(deny appleevent-send)
(deny network*)
(deny file-write* (subpath "/"))
(allow file-write* (subpath "<T>/ws") (literal "<T>/notes.txt") (subpath "<T>/missing") (subpath "<T>/closed/ws"))
(deny file-read* file-write* (subpath "<T>/closed"))
(allow file-read* file-write* (subpath "<T>/closed/ws"))
(allow file-read* (subpath "<T>/closed/proj"))
(deny file-read* file-write* (subpath "<T>/prot") (literal "<T>/prot.key"))
(deny network-outbound (subpath "<T>/prot") (literal "<T>/prot.key"))
(allow file-read* (literal "<T>/copy.txt"))
"""


def test_commands_profile_plain_and_empty(T):
    quoted = T / 'a") (allow default) ("'
    assert _shown(command_sandbox.profile([T / "ws", quoted], []), T) == """\
(version 1)
(allow default)
(deny appleevent-send)
(deny file-write* (subpath "/"))
(allow file-write* (subpath "<T>/ws") (subpath "<T>/a\\") (allow default) (\\""))
"""
    assert command_sandbox.profile([], []) == """\
(version 1)
(allow default)
(deny appleevent-send)
(deny file-write* (subpath "/"))
"""


def test_outside_floor(T, monkeypatch):
    ours = [Path(os.path.realpath(T / "data")), Path(os.path.realpath(T / "updater.key"))]
    monkeypatch.setattr(command_sandbox, "arslan_protected", lambda: ours)
    assert _shown(command_sandbox.minimal_profile(offline=True, copies=[T / "copy.txt"]), T) == """\
(version 1)
(allow default)
(deny appleevent-send)
(deny network*)
(deny file-read* file-write* (subpath "<T>/data") (literal "<T>/updater.key"))
(deny network-outbound (subpath "<T>/data") (literal "<T>/updater.key"))
(allow file-read* (literal "<T>/copy.txt"))
"""
    assert _shown(command_sandbox.minimal_profile(), T) == """\
(version 1)
(allow default)
(deny appleevent-send)
(deny file-read* file-write* (subpath "<T>/data") (literal "<T>/updater.key"))
(deny network-outbound (subpath "<T>/data") (literal "<T>/updater.key"))
"""


def _between_system_and_usr(T: Path) -> None:
    # computation_profile sorts its read paths; the expected texts put <T> between /System and /usr,
    # which holds for the temp roots CI and macOS use (/home/…, /private/var/…, /tmp/…).
    assert Path("/System") < Path(os.path.realpath(T)) < Path("/usr"), os.path.realpath(T)


def test_run_python_and_artifact_checks(T):
    _between_system_and_usr(T)
    python = os.path.join(os.path.realpath(T), "py/bin/python3")
    text = code_sandbox.computation_profile(python, T / "work", T / "refs")
    assert _shown(text, T) == """\
(version 1)
(deny default)
(allow sysctl-read)
(allow file-read-data (literal "/"))
(allow file-read-metadata)
(allow process-fork)
(allow process-info* (target self))
(allow file-read* file-map-executable (subpath "/System/Library"))
(allow file-read* file-map-executable (subpath "/System/Volumes/Preboot/Cryptexes/OS"))
(allow file-read* file-map-executable (subpath "<T>/py/bin"))
(allow file-read* file-map-executable (subpath "<T>/py/lib"))
(allow file-read* file-map-executable (subpath "/usr/lib"))
(allow file-read* file-map-executable (subpath "/usr/share/locale"))
(allow file-read* (literal "/dev/null"))
(allow file-read* (literal "/dev/random"))
(allow file-read* (literal "/dev/urandom"))
(allow file-read* (literal "/private/etc/localtime"))
(allow process-exec (literal "<T>/py/bin/python3"))
(allow file-read* (literal "<T>/py/pyvenv.cfg"))
(allow file-read* file-write* (subpath "<T>/work"))
(allow file-write* (literal "/dev/null"))
(deny file-write* (subpath "<T>/refs"))
"""
    # The artifact checks pass no references: the same text without the last rule.
    assert code_sandbox.computation_profile(python, T / "work") == text[:text.rindex("(deny file-write*")]


def _seed_free(text: str) -> str:
    """With a linked interpreter, computation_profile writes its process-exec lines and its pyvenv.cfg
    lines in set order, which follows the hash seed (SBX-1's check found this on main). Sort each run."""
    lines = text.splitlines()
    for marker in ("(allow process-exec ", "pyvenv.cfg"):
        at = [i for i, line in enumerate(lines) if marker in line]
        assert at == list(range(at[0], at[0] + len(at))), (marker, at)
        lines[at[0]:at[-1] + 1] = sorted(lines[at[0]:at[-1] + 1])
    return "\n".join(lines) + "\n"


def test_run_python_in_a_venv(T):
    _between_system_and_usr(T)
    python = os.path.join(os.path.realpath(T), "venv/bin/python")
    assert _seed_free(_shown(code_sandbox.computation_profile(python, T / "work"), T)) == """\
(version 1)
(deny default)
(allow sysctl-read)
(allow file-read-data (literal "/"))
(allow file-read-metadata)
(allow process-fork)
(allow process-info* (target self))
(allow file-read* file-map-executable (subpath "/System/Library"))
(allow file-read* file-map-executable (subpath "/System/Volumes/Preboot/Cryptexes/OS"))
(allow file-read* file-map-executable (subpath "<T>/py/bin"))
(allow file-read* file-map-executable (subpath "<T>/py/lib"))
(allow file-read* file-map-executable (subpath "<T>/venv/bin"))
(allow file-read* file-map-executable (subpath "<T>/venv/lib"))
(allow file-read* file-map-executable (subpath "/usr/lib"))
(allow file-read* file-map-executable (subpath "/usr/share/locale"))
(allow file-read* (literal "/dev/null"))
(allow file-read* (literal "/dev/random"))
(allow file-read* (literal "/dev/urandom"))
(allow file-read* (literal "/private/etc/localtime"))
(allow process-exec (literal "<T>/py/bin/python3"))
(allow process-exec (literal "<T>/venv/bin/python"))
(allow file-read* (literal "<T>/py/pyvenv.cfg"))
(allow file-read* (literal "<T>/venv/pyvenv.cfg"))
(allow file-read* file-write* (subpath "<T>/work"))
(allow file-write* (literal "/dev/null"))
"""


_MCP_HEAD = """\
(version 1)
(deny default)
(allow process-exec process-fork)
(allow signal (target same-sandbox))
(allow sysctl-read)
(allow mach-lookup)
(allow ipc-posix-shm-read* ipc-posix-shm-write-data)
(allow file-read-metadata)
(allow file-read* (literal "/"))
(allow file-read* (subpath "/usr") (subpath "/System") (subpath "/Library/Apple") (subpath "/Library/Frameworks") \
(subpath "/private/etc") (subpath "/dev") (subpath "/private/var/db/timezone") (subpath "/private/var/db/dyld"))
(allow file-write* (literal "/dev/null"))
"""


def test_installed_mcp_server(T, monkeypatch):
    monkeypatch.setattr(command_sandbox, "default_protected",
                        lambda: [Path(os.path.realpath(T / "prot")), Path(os.path.realpath(T / "prot.key"))])
    text = capability_sandbox.profile(root=T / "mcp", folders=[str(T / "granted"), str(T / "link-granted")],
                                      network=True, read=[str(T / "runtimes")])
    # A protected file is a subpath here, unlike in the commands profile; a granted link appears twice.
    assert _shown(text, T) == _MCP_HEAD + """\
(allow network* system-socket)
(allow file-read* file-write* (subpath "<T>/granted") (subpath "<T>/granted"))
(deny file-read* file-write* network-outbound (subpath "<T>/prot") (subpath "<T>/prot.key"))
(allow file-read* (subpath "<T>/runtimes"))
(allow file-read* file-write* (subpath "<T>/mcp"))
"""
    assert _shown(capability_sandbox.profile(root=T / "mcp", folders=[], network=False, read=[]), T) == _MCP_HEAD + """\
(deny file-read* file-write* network-outbound (subpath "<T>/prot") (subpath "<T>/prot.key"))
(allow file-read* file-write* (subpath "<T>/mcp"))
"""


def test_ssh():
    assert ssh_exec.ssh_profile() == """\
(version 1)
(allow default)
(deny network*)
(allow network-outbound (remote tcp "*:22"))
"""
